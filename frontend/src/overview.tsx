import { Activity, CheckCircle2, CircleAlert, Layers3, MessageSquarePlus, Radio, ShieldCheck, Workflow } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { OverviewData } from './api'
import { Empty, ErrorNotice, Loading, Status, Timestamp } from './components'
import { useApi } from './useApi'

const metrics = [
  { key: 'total', label: 'Total runs', icon: Layers3, tone: 'purple' },
  { key: 'succeeded', label: 'Completed', icon: CheckCircle2, tone: 'green' },
  { key: 'failed', label: 'Failed', icon: CircleAlert, tone: 'red' },
  { key: 'running', label: 'Running', icon: Activity, tone: 'blue' },
  { key: 'awaiting_approval', label: 'Approvals pending', icon: ShieldCheck, tone: 'amber' },
] as const

export function Overview() {
  const { data, error, loading } = useApi<OverviewData>('/api/overview', 5000)
  const success = data?.total ? 100 * data.succeeded / data.total : 0
  const failed = data?.total ? 100 * data.failed / data.total : 0
  const running = data?.total ? 100 * data.running / data.total : 0
  const chart = data?.total
    ? `conic-gradient(#7253e5 0 ${success}%, #ef8d91 ${success}% ${success + failed}%, #73aaff ${success + failed}% ${success + failed + running}%, #e4ae60 ${success + failed + running}% 100%)`
    : '#eeebf7'

  return <>
    <div className="page-heading">
      <h1>Overview</h1>
      <p>Monitor agent runs and pick up where you left off.</p>
    </div>

    <section className="hero" aria-labelledby="overview-hero">
      <div className="hero-content">
        <span className="hero-icon"><Workflow size={19} /></span>
        <h2 id="overview-hero">Run an agent workflow</h2>
        <p>Review overdue tasks, surface blockers, and prepare follow-up drafts.</p>
        <Link className="button hero-button" to="/workspace"><MessageSquarePlus size={18} />Open Agent Workspace</Link>
      </div>
      <div className="hero-art" aria-hidden="true">
        <div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="orbit orbit-three" />
        <i className="orbit-point point-one" /><i className="orbit-point point-two" />
        <div className="hero-node"><Workflow size={44} strokeWidth={1.55} /></div>
      </div>
    </section>

    {error && <ErrorNotice>{error}</ErrorNotice>}
    <div className="metrics" aria-label="Run counts">
      {metrics.map(({ key, label, icon: Icon, tone }) => {
        const content = <>
        <span className={`metric-icon metric-${tone}`}><Icon size={19} /></span>
        <div><div className="metric-label">{label}</div>
          <div className="metric-number tabular-nums">{data ? data[key].toLocaleString() : '—'}</div></div>
        </>
        return key === 'awaiting_approval' ? <Link className="card metric" key={key} to="/approvals">{content}</Link>
          : <div className="card metric" key={key}>{content}</div>
      })}
    </div>

    <div className="overview-grid">
      <section className="card recent-card">
        <div className="card-heading">
          <div><h2>Recent activity</h2><p>Latest workflow runs from your workspace.</p></div>
          <Link className="button button-secondary" to="/trace">View all runs</Link>
        </div>
        {loading && <Loading text="Loading recent activity…" />}
        {data?.recent_runs.length === 0 && <Empty title="No runs yet" detail="Start a workflow in Agent Workspace to see it here." />}
        {data?.recent_runs.map((run) => <Link className="activity-row" to={`/trace?run=${run.id}`} key={run.id}>
          <span className="activity-icon"><Radio size={17} /></span>
          <div className="activity-content"><strong>{run.message}</strong>
            <Timestamp start={run.started_at} end={run.ended_at} /></div>
          <Status status={run.status} />
        </Link>)}
      </section>
      <section className="card outcomes-card">
        <div className="card-heading"><div><h2>Run outcomes</h2><p>All recorded runs</p></div></div>
        <div className="donut" style={{ background: chart }} aria-hidden="true">
          <div><strong>{data?.total.toLocaleString() ?? '—'}</strong><span>Total runs</span></div>
        </div>
        <dl className="chart-legend">
          <div><dt><i className="legend-completed" />Completed</dt><dd>{data?.succeeded ?? '—'}</dd></div>
          <div><dt><i className="legend-failed" />Failed</dt><dd>{data?.failed ?? '—'}</dd></div>
          <div><dt><i className="legend-running" />Running</dt><dd>{data?.running ?? '—'}</dd></div>
          <div><dt><i className="legend-awaiting" />Awaiting approval</dt><dd>{data?.awaiting_approval ?? '—'}</dd></div>
        </dl>
      </section>
    </div>
  </>
}
