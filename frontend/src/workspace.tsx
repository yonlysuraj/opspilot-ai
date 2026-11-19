import { Command, FileText, FolderKanban, ListChecks, MessageSquare, Plus, Send, Workflow } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { startRun, type Conversation, type Run } from './api'
import { Empty, ErrorNotice, formatDate, Loading, Status } from './components'
import { useApi } from './useApi'

const examples = [
  { text: 'Show my overdue tasks, identify the highest-priority blockers, and draft a follow-up for the responsible team members.', label: 'Review overdue blockers', detail: 'Find blockers and draft follow-ups', icon: ListChecks },
  { text: 'What is the status of the Payments Migration project?', label: 'Check project status', detail: 'Review Payments Migration', icon: FolderKanban },
  { text: 'Show my overdue tasks, identify the highest-priority blockers, cite related documents, and draft follow-ups for the responsible people.', label: 'Review blockers with sources', detail: 'Search indexed runbooks and draft follow-ups', icon: FileText },
]

function Turn({ run }: { run: Run }) {
  return <article className="turn">
    <div className="user-turn"><div className="user-bubble">{run.message}</div><span className="profile-avatar">MC</span></div>
    <div className="agent-turn">
      <span className="agent-avatar"><Command size={18} /></span>
      <div className="agent-response">
        <div className="response-heading"><strong>OpsPilot</strong><Status status={run.status} /></div>
        {run.status === 'running' && <Loading text="Processing your request…" />}
        {run.error && <ErrorNotice>{run.error}</ErrorNotice>}
        {run.result && <div className="answer-text">{run.result.answer}</div>}
        {run.result && run.result.citations.length > 0 && <ol className="citations" aria-label="Sources">
          {run.result.citations.map((source, index) => <li key={source.id}>
            <Link className="text-link" to={`/knowledge?source=${source.id}`}>
              <FileText size={15} />[{index + 1}] {source.filename} · {source.location}
            </Link>
          </li>)}
        </ol>}
        {run.approval && <p className="approval-link">
          <Link className="text-link" to={`/approvals?proposal=${run.approval.id}`}>
            {run.approval.status === 'pending' ? 'Review proposed update' : 'View approval decision'}
          </Link>
        </p>}
        {run.result?.projects.map((project) => <section className="project-result" key={project.id}>
          <strong>{project.name}</strong>
          <ul><li>{project.open_tasks} open</li><li>{project.overdue_tasks} overdue</li><li>{project.completed_tasks} completed</li></ul>
          {project.blockers.map((task) => <p key={task.id}>{task.id} · {task.blocker}</p>)}
        </section>)}
        {run.result && run.result.tasks.length > 0 && <details className="draft task-results">
          <summary><ListChecks size={16} /><span><strong>Verified tasks ({run.result.tasks.length})</strong></span></summary>
          <ul>
            {run.result.tasks.map((task) => <li key={task.id}>
              <span className="task-priority">{task.priority}</span>
              <div><strong>{task.id} · {task.title}</strong><small>{task.project} · {task.owner_name} · Due {task.due_on}</small></div>
            </li>)}
          </ul>
        </details>}
        {run.drafts.length > 0 && <div className="drafts">
          <strong>Saved follow-up drafts</strong>
          {run.drafts.map((draft) => <details key={draft.id} className="draft">
            <summary><FileText size={16} /><span><strong>{draft.subject}</strong><small>{draft.recipient_name} · {draft.task_id}</small></span></summary>
            <p>{draft.body}</p>
          </details>)}
        </div>}
        <div className="response-footer">
          {run.trace.length > 0 && <div className="tool-list" aria-label="Tool steps">
            {run.trace.map((step) => <span className={`tool-tag tool-${step.status}`} key={step.id}>{step.tool_name}</span>)}
          </div>}
          <Link className="text-link" to={`/trace?run=${run.id}`}><Workflow size={15} />View trace</Link>
        </div>
      </div>
    </div>
  </article>
}

export function Workspace() {
  const [searchParams, setSearchParams] = useSearchParams()
  const conversationId = searchParams.get('conversation')
  const conversations = useApi<Conversation[]>('/api/conversations', 4000)
  const history = useApi<Run[]>(conversationId ? `/api/conversations/${encodeURIComponent(conversationId)}/runs` : null, 2000)
  const [message, setMessage] = useState('')
  const [submission, setSubmission] = useState<Run>()
  const [submitting, setSubmitting] = useState(false)
  const [sendError, setSendError] = useState<string>()
  const composer = useRef<HTMLTextAreaElement>(null)
  const chatScroll = useRef<HTMLDivElement>(null)
  const pending = submission?.conversation_id === conversationId ? submission : undefined
  const runs = history.data ?? []
  const turns = pending && !runs.some((run) => run.id === pending.id) ? [...runs, pending] : runs
  const waiting = turns.some((run) => run.status === 'awaiting_approval')
  const active = submitting || waiting || turns.some((run) => run.status === 'running')
  const latestTurn = turns.at(-1)?.id

  useEffect(() => {
    if (latestTurn && chatScroll.current) chatScroll.current.scrollTop = chatScroll.current.scrollHeight
  }, [latestTurn, conversationId])

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const prompt = message.trim()
    if (!prompt || active) return
    setSubmitting(true)
    setSendError(undefined)
    try {
      const run = await startRun(prompt, conversationId)
      setSubmission(run)
      setMessage('')
      setSearchParams({ conversation: run.conversation_id })
      history.refresh()
      conversations.refresh()
    } catch (error) {
      setSendError(error instanceof Error ? error.message : 'Could not start a run.')
    } finally {
      setSubmitting(false)
    }
  }

  function switchConversation(id?: string) {
    setSearchParams(id ? { conversation: id } : {})
    setMessage('')
    setSendError(undefined)
  }

  return <>
    <div className="page-heading"><h1>Agent Workspace</h1><p>Talk to OpsPilot and review the work it performs.</p></div>
    <div className="card workspace-grid">
      <aside className="conversations">
        <button className="button button-primary new-chat" onClick={() => switchConversation()} disabled={submitting}>
          <Plus size={18} />New conversation
        </button>
        <h2>Conversations</h2>
        {conversations.loading && <Loading text="Loading…" />}
        {conversations.error && <ErrorNotice>{conversations.error}</ErrorNotice>}
        {conversations.data?.length === 0 && <p className="list-hint">Your conversations will appear here.</p>}
        <div className="conversation-list">
          {conversations.data?.map((item) => <button type="button" className={`conversation-item ${conversationId === item.id ? 'selected' : ''}`}
            onClick={() => switchConversation(item.id)} key={item.id} disabled={submitting}
            aria-current={conversationId === item.id ? 'true' : undefined}>
            <MessageSquare size={16} /><span><strong>{item.title}</strong><small>{formatDate(item.updated_at)}</small></span>
          </button>)}
        </div>
      </aside>
      <section className="chat" aria-label="Conversation">
        <div className="chat-scroll" ref={chatScroll}>
          {!conversationId && <div className="chat-welcome">
            <span className="agent-avatar welcome-icon"><Command size={28} /></span>
            <h2>What can OpsPilot help with?</h2>
            <p>Ask about overdue work, blockers, or project status.</p>
            <div className="samples">
              {examples.map(({ text, label, detail, icon: Icon }) => <button type="button" className="sample" key={label}
                onClick={() => { setMessage(text); composer.current?.focus() }}>
                <Icon size={19} /><span><strong>{label}</strong><small>{detail}</small></span>
              </button>)}
            </div>
          </div>}
          {conversationId && history.loading && !pending && <Loading text="Loading conversation…" />}
          {conversationId && history.error && <ErrorNotice>{history.error}</ErrorNotice>}
          {conversationId && history.data?.length === 0 && <Empty title="No turns to display" detail="Send a message to start this conversation." />}
          {turns.map((run) => <Turn key={run.id} run={run} />)}
        </div>
        <form className="composer" onSubmit={send}>
          {sendError && <ErrorNotice>{sendError}</ErrorNotice>}
          <div className="composer-box">
            <textarea ref={composer} aria-label="Message OpsPilot" placeholder="Message OpsPilot…" rows={2}
              value={message} maxLength={4000} onChange={(event) => setMessage(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault()
                  event.currentTarget.form?.requestSubmit()
                }
              }} />
            <button className="button button-primary send-button" type="submit" disabled={active || !message.trim()} aria-label="Send message">
              <Send size={17} />
            </button>
          </div>
          <p className="composer-hint">{waiting ? 'Review the approval before continuing this conversation.' : 'Enter to send · Shift + Enter for a new line'}</p>
        </form>
      </section>
    </div>
  </>
}
