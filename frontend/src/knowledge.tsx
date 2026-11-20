import { FileText, Search, Upload } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type IndexedDocument, type Source } from './api'
import { Empty, ErrorNotice, formatDate, Loading } from './components'
import { useApi } from './useApi'

export function KnowledgeBase() {
  const [params] = useSearchParams()
  const sourceId = params.get('source')
  const source = useApi<Source>(sourceId ? `/api/knowledge/sources/${encodeURIComponent(sourceId)}` : null)
  const documents = useApi<IndexedDocument[]>('/api/knowledge/documents', 3000)
  const [file, setFile] = useState<File>()
  const [documentBusy, setDocumentBusy] = useState(false)
  const [documentError, setDocumentError] = useState<string>()
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<Source[]>()
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string>()

  async function index(path: string, body?: FormData) {
    setDocumentBusy(true)
    setDocumentError(undefined)
    try {
      const result = await api<IndexedDocument>(path, { method: 'POST', body })
      if (result.error) setDocumentError(result.error)
      documents.refresh()
    } catch (error) {
      setDocumentError(error instanceof Error ? error.message : 'Document indexing failed.')
    } finally {
      setDocumentBusy(false)
    }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || documentBusy) return
    if (file.size > 4 * 1024 * 1024) {
      setDocumentError('Uploads are limited to 4 MB.')
      return
    }
    const form = event.currentTarget
    const body = new FormData()
    body.append('file', file)
    await index('/api/knowledge/documents', body)
    form.reset()
    setFile(undefined)
  }

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!query.trim() || searching) return
    setSearching(true)
    setSearchError(undefined)
    setMatches(undefined)
    try {
      const result = await api<{ items: Source[] }>('/api/knowledge/search', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.trim(), limit: 5 }),
      })
      setMatches(result.items)
    } catch (error) {
      setSearchError(error instanceof Error ? error.message : 'Search failed.')
    } finally {
      setSearching(false)
    }
  }

  return <>
    <div className="page-heading"><h1>Knowledge Base</h1><p>Index project documents and find passages you can cite.</p></div>
    {sourceId && <section className="card knowledge-source section-pad">
      <div className="feature-title"><FileText size={20} /><div><h2>Document source</h2>
        {source.data && <p>{source.data.filename} · {source.data.location}</p>}
      </div><Link className="text-link feature-tail" to="/knowledge">Close source</Link></div>
      {source.loading && <Loading />}
      {source.error && <ErrorNotice>{source.error}</ErrorNotice>}
      {source.data && <blockquote>{source.data.excerpt}</blockquote>}
    </section>}
    <div className="knowledge-grid">
      <section className="card section-pad">
        <div className="feature-title"><Upload size={20} /><div><h2>Upload a document</h2><p>PDF or UTF-8 TXT, up to 4 MB. Use the same filename to update a runbook.</p></div></div>
        <form onSubmit={upload} className="feature-form">
          <label htmlFor="document-file">Document file</label>
          <input id="document-file" type="file" accept=".pdf,.txt,application/pdf,text/plain"
            disabled={documentBusy} onChange={(event) => setFile(event.target.files?.[0])} />
          <button className="button button-primary" disabled={!file || documentBusy} type="submit">
            <Upload size={16} />{documentBusy ? 'Indexing…' : 'Upload and index'}
          </button>
        </form>
        {documentError && <ErrorNotice>{documentError}</ErrorNotice>}
      </section>
      <section className="card section-pad">
        <div className="feature-title"><Search size={20} /><div><h2>Search documents</h2><p>Search the passages in your local index.</p></div></div>
        <form onSubmit={search} className="feature-form">
          <label htmlFor="knowledge-query">Search query</label>
          <div className="input-row"><input id="knowledge-query" value={query} maxLength={500}
            placeholder="e.g. staging rollback" onChange={(event) => setQuery(event.target.value)} />
          <button className="button button-primary" type="submit" disabled={searching || !query.trim()}>Search</button></div>
        </form>
        {searching && <Loading text="Searching indexed documents…" />}
        {searchError && <ErrorNotice>{searchError}</ErrorNotice>}
        {matches?.length === 0 && <Empty title="No matching passages" detail="Try another query or index a related document." />}
        {matches && matches.length > 0 && <ul className="search-results">{matches.map((match) => <li key={match.id}>
          <Link className="text-link" to={`/knowledge?source=${match.id}`}>{match.filename} · {match.location}</Link>
          <p>{match.excerpt}</p>
        </li>)}</ul>}
      </section>
    </div>
    <section className="card section-pad documents">
      <div className="feature-title"><FileText size={20} /><div><h2>Documents</h2><p>Indexing status and passage counts</p></div></div>
      {documents.loading && <Loading />}
      {documents.error && <ErrorNotice>{documents.error}</ErrorNotice>}
      {documents.data?.length === 0 && <Empty title="No documents yet" detail="Upload a project runbook or other reference to get started." />}
      {documents.data?.map((document) => <div className="document-row" key={document.id}>
        <div><strong>{document.filename}</strong><p>{document.chunk_count} passages · {formatDate(document.updated_at)}</p>
          {document.error && <p className="document-error">{document.error}</p>}</div>
        <span className={`status status-${document.status === 'indexed' ? 'succeeded' : document.status === 'indexing' ? 'running' : 'failed'}`}>
          {document.status}
        </span>
        {document.status === 'failed' && <button className="button button-secondary" disabled={documentBusy}
          onClick={() => void index(`/api/knowledge/documents/${document.id}/retry`)}>Retry</button>}
      </div>)}
    </section>
  </>
}
