import { CalendarDays, Check, CircleAlert, Clock3, LoaderCircle, ShieldCheck, Terminal } from 'lucide-react'
import type { ReactNode } from 'react'
import type { RunStatus } from './api'

const labels = { running: 'Running', awaiting_approval: 'Awaiting approval', succeeded: 'Completed', failed: 'Failed' }

export function Status({ status }: { status: RunStatus }) {
  const Icon = status === 'running' ? LoaderCircle : status === 'succeeded' ? Check
    : status === 'awaiting_approval' ? ShieldCheck : CircleAlert
  return <span className={`status status-${status}`}><Icon size={13} />{labels[status]}</span>
}

export function ErrorNotice({ children }: { children: ReactNode }) {
  return <div className="error-notice" role="alert"><CircleAlert size={17} /><div>{children}</div></div>
}

export function Empty({ title, detail }: { title: string; detail: string }) {
  return <div className="empty"><span className="empty-icon"><Terminal size={20} /></span>
    <strong>{title}</strong><p>{detail}</p>
  </div>
}

export function Loading({ text = 'Loading…' }: { text?: string }) {
  return <div className="loading" role="status"><LoaderCircle size={19} className="spinner" />{text}</div>
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  }).format(new Date(value))
}

export function formatDuration(milliseconds: number) {
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`
  if (milliseconds < 60_000) return `${(milliseconds / 1000).toFixed(1)} s`
  return `${Math.floor(milliseconds / 60_000)}m ${Math.round((milliseconds % 60_000) / 1000)}s`
}

export function Timestamp({ start, end }: { start: string; end?: string | null }) {
  return <div className="timestamp"><span><CalendarDays size={14} />{formatDate(start)}</span>
    {end && <span><Clock3 size={14} />{formatDuration(new Date(end).getTime() - new Date(start).getTime())}</span>}
  </div>
}
