from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

TaskId = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2,10}-[0-9]{1,8}$")]
Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
DraftSubject = Annotated[Message, Field(max_length=160)]
DraftBody = Annotated[Message, Field(max_length=2000)]
ProjectKey = Annotated[Message, Field(max_length=100)]
RunStatus = Literal["running", "awaiting_approval", "succeeded", "failed"]
WorkflowName = Literal["overdue_blocker_followups", "project_status", "knowledge", "task_update", "general"]
TaskStatus = Literal["open", "in_progress", "done"]


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ListTasks(ToolArguments):
    filter: Literal["overdue", "open", "all"] = "overdue"


class GetTask(ToolArguments):
    task_id: TaskId


class CreateDraft(GetTask):
    subject: DraftSubject
    body: DraftBody


class GetProject(ToolArguments):
    project: ProjectKey


class RequestPlan(ToolArguments):
    workflow: WorkflowName
    project: ProjectKey | None = None
    task_id: str | None = None
    new_status: TaskStatus | None = None


class SearchDocuments(ToolArguments):
    query: Annotated[Message, Field(max_length=500)]
    limit: int = Field(default=3, ge=1, le=5)


class ProposeTaskUpdate(GetTask):
    new_status: TaskStatus


class Source(BaseModel):
    id: str
    document_id: str
    filename: str
    location: str
    excerpt: str


class SearchResults(BaseModel):
    items: list[Source]


class Document(BaseModel):
    id: str
    filename: str
    format: Literal["pdf", "txt"]
    status: Literal["indexing", "indexed", "failed"]
    chunk_count: int
    error: str | None
    created_at: datetime
    updated_at: datetime


class Approval(BaseModel):
    id: UUID
    run_id: UUID
    requester_id: str
    action: Literal["task_status_update"]
    task_id: TaskId
    previous_status: TaskStatus
    new_status: TaskStatus
    status: Literal["pending", "approved", "rejected", "cancelled"]
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    run_status: RunStatus | None = None


class ApprovalDecision(ToolArguments):
    decision: Literal["approved", "rejected"]


class FollowupDrafts(ToolArguments):
    drafts: list[CreateDraft]


class Task(BaseModel):
    id: TaskId
    title: str
    project: str
    owner_name: str
    priority: Literal["P0", "P1", "P2", "P3"]
    status: TaskStatus
    due_on: date
    blocker: str | None


class TaskList(BaseModel):
    tasks: list[Task]


class ProjectStatus(BaseModel):
    id: str
    name: str
    total_tasks: int
    open_tasks: int
    completed_tasks: int
    overdue_tasks: int
    blockers: list[Task]


class Draft(BaseModel):
    id: str
    task_id: TaskId
    recipient_name: str
    subject: str
    body: str
    status: Literal["draft"]


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[Message, Field(max_length=4000)]
    conversation_id: UUID | None = None


class RunResult(BaseModel):
    answer: str
    tasks: list[Task]
    priority_blockers: list[Task]
    projects: list[ProjectStatus] = Field(default_factory=list)
    citations: list[Source] = Field(default_factory=list)
    approval_id: UUID | None = None


class RunStep(BaseModel):
    id: int
    tool_name: str
    started_at: datetime
    ended_at: datetime
    duration_ms: float
    status: Literal["succeeded", "failed"]
    error: str | None


class RunSummary(BaseModel):
    id: UUID
    conversation_id: UUID
    requester_id: str
    message: str
    status: RunStatus
    started_at: datetime
    ended_at: datetime | None
    duration_ms: float | None = None
    error: str | None


class RunRecord(RunSummary):
    result: RunResult | None
    drafts: list[Draft]
    trace: list[RunStep]
    approval: Approval | None = None


class ConversationSummary(BaseModel):
    id: UUID
    title: str
    latest_run_id: UUID
    updated_at: datetime
    status: RunStatus
    run_count: int


class Overview(BaseModel):
    total: int
    succeeded: int
    failed: int
    running: int
    awaiting_approval: int = 0
    recent_runs: list[RunSummary]
