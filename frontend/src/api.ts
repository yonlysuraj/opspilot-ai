export type RunStatus = 'running' | 'awaiting_approval' | 'succeeded' | 'failed'

export type Source = {
  id: string
  document_id: string
  filename: string
  location: string
  excerpt: string
}

export type IndexedDocument = {
  id: string
  filename: string
  format: 'pdf' | 'txt'
  status: 'indexing' | 'indexed' | 'failed'
  chunk_count: number
  error: string | null
  updated_at: string
}

export type Approval = {
  id: string
  run_id: string
  task_id: string
  previous_status: string
  new_status: string
  status: 'pending' | 'approved' | 'rejected' | 'cancelled'
  created_at: string
  decided_at: string | null
  decided_by: string | null
  run_status?: RunStatus | null
}

export type Task = {
  id: string
  title: string
  project: string
  owner_name: string
  priority: string
  status: string
  due_on: string
  blocker: string | null
}

export type Project = {
  id: string
  name: string
  total_tasks: number
  open_tasks: number
  completed_tasks: number
  overdue_tasks: number
  blockers: Task[]
}

export type Draft = {
  id: string
  task_id: string
  recipient_name: string
  subject: string
  body: string
}

export type RunStep = {
  id: number
  tool_name: string
  status: 'succeeded' | 'failed'
  started_at: string
  ended_at: string
  duration_ms: number
  error: string | null
}

export type RunSummary = {
  id: string
  conversation_id: string
  message: string
  status: RunStatus
  started_at: string
  ended_at: string | null
  duration_ms: number | null
  error: string | null
}

export type Run = RunSummary & {
  result: { answer: string; tasks: Task[]; priority_blockers: Task[]; projects: Project[]; citations: Source[] } | null
  drafts: Draft[]
  trace: RunStep[]
  approval: Approval | null
}

export type Conversation = {
  id: string
  title: string
  latest_run_id: string
  updated_at: string
  status: RunStatus
  run_count: number
}

export type OverviewData = {
  total: number
  succeeded: number
  failed: number
  running: number
  awaiting_approval: number
  recent_runs: RunSummary[]
}

export type Health = {
  status: 'ready' | 'unavailable'
  demo_data: string
  ollama: { status: string; model?: string; detail?: string }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', ...init })
  const json = await response.json().catch(() => null)
  if (!response.ok && !(path === '/health/ready' && response.status === 503 && json?.ollama)) {
    throw new Error(typeof json?.detail === 'string' ? json.detail : (
      response.status >= 500 ? 'Could not reach the OpsPilot API. Check that FastAPI is running.' :
        `The request was rejected (HTTP ${response.status}).`
    ))
  }
  if (json === null) throw new Error('The OpsPilot API returned an unreadable response.')
  return json as T
}

export function startRun(message: string, conversationId: string | null) {
  return api<Run>('/api/runs?background=true', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  })
}
