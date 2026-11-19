import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Query, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from .agent import AgentFailure, ChatModel, run_agent
from .approval_flow import check_approval, pause_approval, resume_approval
from .config import DEMO_USER, Settings
from .events import configure_events, emit
from .knowledge import MAX_UPLOAD, Knowledge, KnowledgeError
from .models import (
    Approval, ApprovalDecision, ConversationSummary, Document, Overview, RunRecord, RunRequest,
    RunStatus, RunSummary, SearchDocuments, SearchResults, Source,
)
from .ollama import Ollama
from .storage import ApprovalConflict, RunInProgress, Store

def create_app(settings: Settings | None = None, model: ChatModel | None = None) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.db_path)
    ollama = Ollama(settings)
    model = model or ollama
    knowledge = Knowledge(settings, store)
    decision_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_events()
        store.initialize()
        store.fail_interrupted_runs()
        for proposal in store.approvals(DEMO_USER, decided_waiting=True):
            try:
                await check_approval(settings, proposal)
                await resume_approval(settings, store, proposal)
            except Exception:
                emit("approval_resume_failed", run_id=str(proposal.run_id), approval_id=str(proposal.id),
                     error_code="startup_recovery")
        yield

    app = FastAPI(title="OpsPilot AI", version="0.1.0", lifespan=lifespan)

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready(response: Response) -> dict:
        seeded = store.is_seeded()
        model_status = await ollama.readiness()
        available = seeded and model_status["status"] == "ready"
        if not available:
            response.status_code = 503
        return {
            "status": "ready" if available else "unavailable",
            "demo_data": "ready" if seeded else "Run: python -m opspilot.seed",
            "ollama": model_status,
        }

    @app.get("/api/overview", response_model=Overview)
    def overview() -> dict:
        return store.overview(DEMO_USER)

    @app.get("/api/knowledge/documents", response_model=list[Document])
    def documents() -> list[Document]:
        return knowledge.documents(DEMO_USER)

    @app.post("/api/knowledge/documents", response_model=Document, max_body_size=MAX_UPLOAD + 64 * 1024)
    async def upload_document(file: UploadFile = File(...)) -> Document:
        try:
            raw = await file.read(MAX_UPLOAD + 1)
            if len(raw) > MAX_UPLOAD:
                raise HTTPException(status_code=413, detail="Uploads are limited to 4 MB.")
            return await run_in_threadpool(knowledge.upload, DEMO_USER, file.filename or "", raw)
        except KnowledgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            await file.close()

    @app.post("/api/knowledge/documents/{doc_id}/retry", response_model=Document)
    def retry_document(doc_id: str) -> Document:
        try:
            return knowledge.index(DEMO_USER, doc_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/knowledge/search", response_model=SearchResults)
    def search_documents(request: SearchDocuments) -> SearchResults:
        try:
            return knowledge.search(DEMO_USER, request.query, request.limit)
        except KnowledgeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/knowledge/sources/{source_id}", response_model=Source)
    def get_source(source_id: str) -> Source:
        source = knowledge.source(DEMO_USER, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Document source not found.")
        return source

    @app.get("/api/approvals", response_model=list[Approval])
    def approvals() -> list[Approval]:
        return store.approvals(DEMO_USER)

    @app.post("/api/approvals/{approval_id}/decision", response_model=Approval)
    async def decide(
        approval_id: UUID, request: ApprovalDecision, authorization: str | None = Header(default=None),
    ) -> Approval:
        token = settings.approver_token.get_secret_value()
        if len(token) < 32:
            raise HTTPException(status_code=503, detail="Configure OPSPILOT_APPROVER_TOKEN to enable decisions.")
        if not authorization or not secrets.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
            emit("approval_denied", approval_id=str(approval_id), error_code="unauthorized")
            raise HTTPException(status_code=401, detail="A valid approver token is required.",
                                headers={"WWW-Authenticate": "Bearer"})
        async with decision_lock:
            proposal = store.get_approval(DEMO_USER, str(approval_id))
            if proposal is None:
                raise HTTPException(status_code=404, detail="Approval not found.")
            try:
                if proposal.status == "pending":
                    await check_approval(settings, proposal)
                decision = store.decide_approval(DEMO_USER, str(approval_id), request.decision, "local-approver")
                assert decision is not None
                if proposal.status == request.decision:
                    emit("approval_replay", run_id=str(decision.run_id), approval_id=str(decision.id),
                         status=decision.status)
                await resume_approval(settings, store, decision)
                return decision
            except ApprovalConflict as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except Exception as exc:
                emit("approval_resume_failed", run_id=str(proposal.run_id), approval_id=str(approval_id),
                     error_code="decision_processing")
                raise HTTPException(status_code=503, detail="Could not resume the workflow. Retry the same decision.") from exc

    @app.get("/api/runs", response_model=list[RunSummary])
    def list_runs(
        limit: int = Query(30, ge=1, le=100), status: RunStatus | None = None,
    ) -> list[dict]:
        return store.run_summaries(DEMO_USER, limit, status)

    @app.get("/api/conversations", response_model=list[ConversationSummary])
    def list_conversations(limit: int = Query(30, ge=1, le=100)) -> list[dict]:
        return store.conversation_summaries(DEMO_USER, limit)

    @app.get("/api/conversations/{conversation_id}/runs", response_model=list[RunRecord])
    def conversation_runs(conversation_id: UUID, limit: int = Query(30, ge=1, le=50)) -> list[dict]:
        runs = store.conversation_runs(DEMO_USER, str(conversation_id), limit)
        if not runs:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return runs

    @app.get("/api/runs/{run_id}", response_model=RunRecord)
    def get_run(run_id: UUID) -> dict:
        run = store.get_run(DEMO_USER, str(run_id))
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return run

    @app.post(
        "/api/runs", status_code=201, response_model=RunRecord,
        responses={202: {"model": RunRecord, "description": "Run accepted for background execution"}},
    )
    async def create_run(
        request: RunRequest, response: Response, tasks: BackgroundTasks, background: bool = False,
    ) -> dict:
        if not store.is_seeded():
            raise HTTPException(status_code=503, detail="Run: python -m opspilot.seed")
        conversation_id = str(request.conversation_id or uuid4())
        try:
            run_id = store.start_run(DEMO_USER, conversation_id, request.message)
        except RunInProgress as exc:
            raise HTTPException(status_code=409, detail="This conversation already has an active run.") from exc
        if background:
            response.status_code = 202
            tasks.add_task(execute_run, run_id, conversation_id, request.message)
        else:
            await execute_run(run_id, conversation_id, request.message)
        return get_run(UUID(run_id))

    async def execute_run(run_id: str, conversation_id: str, message: str) -> None:
        result = None
        error = None
        paused = False
        try:
            history = store.history(DEMO_USER, conversation_id)
            result = await run_agent(settings, store, model, DEMO_USER, run_id, conversation_id, [
                *history, {"role": "user", "content": message},
            ])
            if result.approval_id:
                proposal = store.get_approval(DEMO_USER, str(result.approval_id))
                if proposal is None:
                    raise AgentFailure("The task proposal could not be loaded.")
                await pause_approval(settings, proposal)
                store.pause_run(run_id, result)
                paused = True
        except AgentFailure as exc:
            error = str(exc)
        except asyncio.CancelledError:
            error = "The workflow was interrupted."
            raise
        except Exception:
            error = "The workflow could not complete. Inspect the run trace for completed steps."
        finally:
            if not paused:
                store.finish_run(run_id, result, error)
    return app


app = create_app()
