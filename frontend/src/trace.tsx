import { ArrowDown, Clock3, CodeXml, MessageSquare, Workflow } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { Run, RunStatus, RunSummary } from './api'
import { Empty, ErrorNotice, formatDate, formatDuration, Loading, Status, Timestamp } from './components'
import { useApi } from './useApi'

const filters = [
  { key: 'all', label: 'All' },
  { key: 'running', label: 'Running' },
  { key: 'awaiting_approval', label: 'Awaiting approval' },
  { key: 'succeeded', label: 'Completed' },
  { key: 'failed', label: 'Failed' },
] as const

function RunDetail({ run }: { run: Run }) {
  return <div className="run-detail">
    <div className="run-title">
      <div><span className="run-label">Run details</span><h2>{run.message}</h2></div>
      <Status status={run.status} />
    </div>
    <div className="run-meta">
      <Timestamp start={run.started_at} end={run.ended_at} />
      <span className="run-id">Run ID <code>{run.id}</code></span>
    </div>
    {run.error && <ErrorNotice>{run.error}</ErrorNotice>}
    {run.approval && <div className="trace-approval">
      <strong>{run.approval.task_id} · {run.approval.previous_status.replaceAll('_', ' ')} to {run.approval.new_status.replaceAll('_', ' ')}</strong>
      <Link className="text-link" to={`/approvals?proposal=${run.approval.id}`}>Approval {run.approval.status}</Link>
    </div>}
    <div className="timeline-header">
      <div><h3>MCP tool calls</h3><p>{run.trace.length} recorded {run.trace.length === 1 ? 'step' : 'steps'}</p></div>
      <Link className="button button-secondary" to={`/workspace?conversation=${run.conversation_id}`}>
        <MessageSquare size={17} />Open conversation
      </Link>
    </div>
    {run.trace.length === 0 && (run.status === 'running'
      ? <Loading text="Waiting for the first tool result…" />
      : <Empty title="No tool calls recorded" detail="This run finished without a recorded tool step." />)}
    <ol className="timeline">
      {run.trace.map((step) => <li className="timeline-step" key={step.id}>
        <span className="timeline-icon"><CodeXml size={17} /></span>
        <div className="step-content">
          <div className="step-main"><strong>{step.tool_name}</strong><Status status={step.status} /></div>
          <div className="timestamp"><span>Step #{step.id}</span><span>{formatDate(step.started_at)}</span><span><Clock3 size={13} />{formatDuration(step.duration_ms)}</span></div>
          {step.error && <ErrorNotice>{step.error}</ErrorNotice>}
        </div>
      </li>)}
    </ol>
  </div>
}

export function Trace() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedRun = searchParams.get('run')
  const [filter, setFilter] = useState<'all' | RunStatus>('all')
  const runList = useApi<RunSummary[]>(`/api/runs?limit=50${filter === 'all' ? '' : `&status=${filter}`}`, 4000)
  const selected = requestedRun ?? runList.data?.[0]?.id
  const details = useApi<Run>(selected ? `/api/runs/${encodeURIComponent(selected)}` : null, 2200)

  return <>
    <div className="page-heading"><h1>Workflow Trace</h1><p>Inspect each run, its tool calls, and any errors.</p></div>
    <div className="trace-grid">
      <section className="card run-list">
        <div className="card-heading"><div><h2>Run history</h2><p>Newest first <ArrowDown size={12} /></p></div></div>
        <div className="run-filters" aria-label="Filter runs">
          {filters.map(({ key, label }) => <button type="button" aria-pressed={filter === key}
            onClick={() => { setFilter(key); setSearchParams({}) }} key={key}>{label}</button>)}
        </div>
        {runList.loading && <Loading text="Loading runs…" />}
        {runList.error && <ErrorNotice>{runList.error}</ErrorNotice>}
        {runList.data?.length === 0 && <Empty title="No matching runs" detail="Choose another filter or start a workflow." />}
        <div className="run-items">
          {runList.data?.map((run) => <button type="button" key={run.id} onClick={() => setSearchParams({ run: run.id })}
            aria-current={run.id === selected ? 'true' : undefined} className={`run-item ${run.id === selected ? 'selected' : ''}`}>
            <strong>{run.message}</strong><div><span>{formatDate(run.started_at)}</span><Status status={run.status} /></div>
          </button>)}
        </div>
      </section>
      <section className="card trace-detail">
        {details.loading && <Loading text="Loading trace…" />}
        {details.error && <ErrorNotice>{details.error}</ErrorNotice>}
        {details.data && <RunDetail run={details.data} />}
        {!selected && !runList.loading && <div className="unselected-trace">
          <span className="agent-avatar"><Workflow size={22} /></span>
          <h2>Select a run</h2><p>Run details and tool calls will appear here.</p>
        </div>}
      </section>
    </div>
  </>
}
