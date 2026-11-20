import hashlib
import io
from collections.abc import Iterator
from pathlib import PurePosixPath

import httpx
from filelock import FileLock
from pypdf import PdfReader

from .config import Settings
from .events import emit
from .models import Document, SearchResults, Source
from .storage import Store, utc_now

MAX_UPLOAD = 4 * 1024 * 1024
MAX_CHUNKS = 180
DOC_COLUMNS = "id, filename, format, status, chunk_count, error, created_at, updated_at"


class KnowledgeError(Exception):
    """A knowledge-base error safe to display to the requester."""


def extract_chunks(raw: bytes, kind: str) -> list[tuple[str, str]]:
    def parts() -> Iterator[tuple[str, str]]:
        if kind == "txt":
            lines = raw.decode("utf-8-sig").splitlines()
            for start in range(0, len(lines), 15):
                end = min(start + 15, len(lines))
                yield f"Lines {start + 1}–{end}", "\n".join(lines[start:end])
        else:
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted or len(reader.pages) > 60:
                raise KnowledgeError("Use an unencrypted PDF with at most 60 pages.")
            for index, page in enumerate(reader.pages, 1):
                yield f"Page {index}", page.extract_text() or ""

    chunks = []
    try:
        for location, part in parts():
            if "\x00" in part or len(part) > 160_000:
                raise KnowledgeError("This document section is too large or contains binary text.")
            text = " ".join(part.split())
            if not text:
                continue
            for start in range(0, len(text), 760):
                excerpt = text[max(0, start - 90):start + 760]
                chunks.append((location, excerpt))
                if len(chunks) > MAX_CHUNKS:
                    raise KnowledgeError("This document contains too much text. Upload a shorter file.")
    except KnowledgeError:
        raise
    except Exception as exc:
        raise KnowledgeError("Could not extract text. Use UTF-8 TXT or an unencrypted PDF with selectable text.") from exc
    if not chunks:
        raise KnowledgeError("No readable text was found. Scanned PDFs require OCR before upload.")
    return chunks


class Knowledge:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store
        self.directory = settings.vector_path

    def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        model = self.settings.embedding_model
        prefix = ("search_query: " if query else "search_document: ") if model.startswith("nomic-embed-text") else ""
        try:
            with httpx.Client(base_url=self.settings.ollama_url, timeout=60, trust_env=False) as client:
                response = client.post("/api/embed", json={"model": model, "input": [prefix + text for text in texts]})
                if response.status_code == 404:
                    raise KnowledgeError(f"Embedding model is missing. Run ollama pull {model}.")
                response.raise_for_status()
                embeddings = response.json()["embeddings"]
                if len(embeddings) != len(texts) or not all(embeddings):
                    raise ValueError("Invalid embedding batch.")
                return embeddings
        except KnowledgeError:
            raise
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            raise KnowledgeError("Ollama could not generate local embeddings.") from exc

    def vector_lock(self) -> FileLock:
        self.directory.mkdir(parents=True, exist_ok=True)
        return FileLock(str(self.directory / "process.lock"), timeout=30)

    def collection(self, *, create: bool):
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        client = chromadb.PersistentClient(
            path=str(self.directory), settings=ChromaSettings(anonymized_telemetry=False)
        )
        name = "knowledge-" + hashlib.sha256(self.settings.embedding_model.encode()).hexdigest()[:16]
        if create:
            return client.get_or_create_collection(
                name, embedding_function=None, configuration={"hnsw": {"space": "cosine"}},
            )
        return client.get_collection(name, embedding_function=None)

    def documents(self, requester: str) -> list[Document]:
        with self.store.connect() as db:
            return [Document.model_validate(dict(row)) for row in db.execute(
                f"SELECT {DOC_COLUMNS} FROM documents WHERE requester_id = ? ORDER BY created_at DESC",
                (requester,),
            )]

    def upload(self, requester: str, filename: str, raw: bytes) -> Document:
        filename = PurePosixPath(filename.replace("\\", "/")).name
        kind = filename.rsplit(".", 1)[-1].lower()
        if kind not in {"pdf", "txt"} or "." not in filename or not raw or len(filename) > 160:
            raise KnowledgeError("Upload a nonempty PDF or TXT with a filename up to 160 characters.")
        if len(raw) > MAX_UPLOAD:
            raise KnowledgeError("Uploads are limited to 4 MB.")
        namespace = requester.encode() + b"\0" + kind.encode() + b"\0"
        legacy_id = hashlib.sha256(namespace + raw).hexdigest()[:32]
        doc_id = hashlib.sha256(b"\0revision\0" + namespace + filename.encode() + b"\0" + raw).hexdigest()[:32]
        now = utc_now()
        with self.store.connect() as db:
            legacy = db.execute(
                "SELECT id FROM documents WHERE id = ? AND requester_id = ? AND filename = ?",
                (legacy_id, requester, filename),
            ).fetchone()
            if legacy:
                doc_id = legacy["id"]
            db.execute(
                """INSERT INTO documents (id, requester_id, filename, format, model, raw, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'failed', ?, ?) ON CONFLICT (id) DO NOTHING""",
                (doc_id, requester, filename, kind, self.settings.embedding_model, raw, now, now),
            )
        return self.index(requester, doc_id)

    def index(self, requester: str, doc_id: str) -> Document:
        model = self.settings.embedding_model
        with self.store.connect() as db:
            claimed = db.execute(
                """UPDATE documents SET status = 'indexing', model = ?, updated_at = ?, error = NULL, chunk_count = 0
                WHERE id = ? AND requester_id = ? AND status <> 'indexing'
                AND (status = 'failed' OR model <> ?)""", (model, utc_now(), doc_id, requester, model),
            ).rowcount
            document = db.execute(
                "SELECT * FROM documents WHERE id = ? AND requester_id = ?", (doc_id, requester),
            ).fetchone()
        if document is None:
            raise LookupError("Document not found.")
        if not claimed:
            return Document.model_validate(dict(document))
        started = utc_now()
        try:
            chunks = extract_chunks(document["raw"], document["format"])
            ids = [f"{doc_id}-{index}" for index in range(len(chunks))]
            texts = [text for _, text in chunks]
            vectors = []
            for start in range(0, len(texts), 32):
                vectors.extend(self.embed(texts[start:start + 32]))
            with self.vector_lock():
                collection = self.collection(create=True)
                collection.upsert(
                    ids=ids, embeddings=vectors, documents=texts,
                    metadatas=[{"document_id": doc_id} for _ in chunks],
                )
            with self.store.connect() as db:
                db.execute("DELETE FROM document_chunks WHERE document_id = ?", (doc_id,))
                db.executemany(
                    "INSERT INTO document_chunks VALUES (?, ?, ?, ?)",
                    ((key, doc_id, location, excerpt) for key, (location, excerpt) in zip(ids, chunks, strict=True)),
                )
                db.execute(
                    "UPDATE documents SET status = 'indexed', chunk_count = ?, updated_at = ? WHERE id = ?",
                    (len(chunks), utc_now(), doc_id),
                )
            emit("document_indexed", document_id=doc_id, status="indexed", started_at=started,
                 ended_at=utc_now(), chunk_count=len(chunks))
        except Exception as exc:
            error = str(exc) if isinstance(exc, KnowledgeError) else "Indexing failed. Retry this document."
            with self.store.connect() as db:
                db.execute(
                    "UPDATE documents SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                    (error, utc_now(), doc_id),
                )
            emit("document_index_failed", document_id=doc_id, status="failed", started_at=started,
                 ended_at=utc_now(), error_code="indexing_failed")
        with self.store.connect() as db:
            row = db.execute(f"SELECT {DOC_COLUMNS} FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return Document.model_validate(dict(row))

    def source(self, requester: str, chunk_id: str) -> Source | None:
        with self.store.connect() as db:
            row = db.execute(
                """SELECT c.id, d.id AS document_id, d.filename, c.location, c.excerpt
                FROM document_chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.id = ? AND d.requester_id = ?""",
                (chunk_id, requester),
            ).fetchone()
        return Source.model_validate(dict(row)) if row else None

    def search(self, requester: str, query: str, limit: int) -> SearchResults:
        with self.store.connect() as db:
            ids = [row["id"] for row in db.execute(
                """SELECT d.id FROM documents d
                WHERE d.requester_id = ? AND d.status = 'indexed' AND d.model = ?
                  AND NOT EXISTS (
                    SELECT 1 FROM documents newer
                    WHERE newer.requester_id = d.requester_id AND newer.filename = d.filename
                      AND newer.rowid > d.rowid
                      AND EXISTS (SELECT 1 FROM document_chunks c WHERE c.document_id = newer.id)
                  )""",
                (requester, self.settings.embedding_model),
            )]
        if not ids:
            return SearchResults(items=[])
        embeds = self.embed([query], query=True)
        try:
            with self.vector_lock():
                results = self.collection(create=False).query(
                    query_embeddings=embeds, n_results=limit, where={"document_id": {"$in": ids}},
                    include=["distances"],
                )
        except Exception as exc:
            raise KnowledgeError("The local document index could not be queried.") from exc
        matches = [
            self.source(requester, key)
            for key, distance in zip(results["ids"][0], results["distances"][0], strict=True)
            if distance < 0.85
        ]
        return SearchResults(items=[source for source in matches if source is not None])
