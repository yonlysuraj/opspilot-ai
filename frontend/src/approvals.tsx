import { ShieldCheck, Workflow } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type Approval } from './api'
import { Empty, ErrorNotice, formatDate, Loading } from './components'
import { useApi } from './useApi'

type Decision = 'approved' | 'rejected'

export function Approvals() {
  const [params] = useSearchParams()
  const selected = params.get('proposal')
  const approvals = useApi<Approval[]>('/api/approvals', 2500)
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState<string>()
  const [error, setError] = useState<string>()
  const pending = approvals.data?.filter((item) => item.status === 'pending') ?? []
  const history = approvals.data?.filter((item) => item.status !== 'pending') ?? []

  async function decide(id: string, decision: Decision) {
    if (!token || busy) return
    setBusy(id)
    setError(undefined)
    try {
      await api<Approval>(`/api/approvals/${id}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ decision }),
      })
      setToken('')
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not record the decision.')
    } finally {
      setBusy(undefined)
      approvals.refresh()
    }
  }

  function entry(item: Approval) {
    const canDecide = Boolean(token) && !busy && item.run_status === 'awaiting_approval'
    return <article className={`approval-row ${selected === item.id ? 'approval-selected' : ''}`} key={item.id}>
      <div>
        <div className="approval-heading"><strong>{item.task_id} · Task status update</strong>
          <span className={`status status-${({ pending: 'awaiting_approval', approved: 'succeeded', rejected: 'failed', cancelled: 'failed' })[item.status]}`}>
            {item.status}</span></div>
        <p>{item.previous_status.replaceAll('_', ' ')} → <b>{item.new_status.replaceAll('_', ' ')}</b></p>
        <p>{item.decided_at ? `${formatDate(item.decided_at)} · ${item.decided_by}` : `Requested ${formatDate(item.created_at)}`}</p>
        <Link className="text-link" to={`/trace?run=${item.run_id}`}><Workflow size={15} />View trace</Link>
      </div>
      {item.status === 'pending' && <div className="approval-actions">
        <button className="button button-secondary" disabled={!canDecide}
          onClick={() => void decide(item.id, 'rejected')}>Reject</button>
        <button className="button button-primary" disabled={!canDecide}
          onClick={() => void decide(item.id, 'approved')}>{busy === item.id ? 'Saving…' : 'Approve update'}</button>
      </div>}
      {item.run_status === 'awaiting_approval' && (item.status === 'approved' || item.status === 'rejected') &&
        <button className="button button-secondary" disabled={!token || Boolean(busy)}
          onClick={() => void decide(item.id, item.status as Decision)}>Retry resume</button>}
    </article>
  }

  return <>
    <div className="page-heading"><h1>Approval Center</h1><p>Review the exact task change before making a decision.</p></div>
    <section className="card section-pad approval-section">
      <div className="feature-title"><ShieldCheck size={20} /><div><h2>Pending approvals</h2>
        <p>Task status changes require an approver token.</p></div></div>
      <div className="feature-form approval-token">
        <label htmlFor="approver-token">Approver token</label>
        <input id="approver-token" type="password" autoComplete="off" value={token} maxLength={256}
          onChange={(event) => setToken(event.target.value)} />
      </div>
      {approvals.loading && <Loading />}
      {(error || approvals.error) && <ErrorNotice>{error ?? approvals.error}</ErrorNotice>}
      {approvals.data && pending.length === 0 && <Empty title="No pending approvals" detail="Proposed task updates will appear here." />}
      {pending.map(entry)}
    </section>
    <section className="card section-pad approval-section">
      <div className="feature-title"><ShieldCheck size={20} /><div><h2>Decision history</h2><p>Recorded decisions and linked workflow runs</p></div></div>
      {approvals.data && history.length === 0 && <Empty title="No decisions yet" detail="Approved and rejected proposals will appear here." />}
      {history.map(entry)}
    </section>
  </>
}
