import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .config import DEMO_USER
from .events import elapsed_ms, emit
from .models import Approval, CreateDraft, Draft, ProjectStatus, ProposeTaskUpdate, RunResult, RunStatus, Task

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id TEXT PRIMARY KEY, name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY, title TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(id),
    requester_id TEXT NOT NULL REFERENCES employees(id),
    owner_id TEXT NOT NULL REFERENCES employees(id),
    priority TEXT NOT NULL CHECK (priority IN ('P0', 'P1', 'P2', 'P3')),
    status TEXT NOT NULL CHECK (status IN ('open', 'in_progress', 'done')),
    due_on TEXT NOT NULL, blocker TEXT
);
CREATE INDEX IF NOT EXISTS tasks_requester ON tasks(requester_id, due_on);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, requester_id TEXT NOT NULL,
    message TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
    ended_at TEXT, result_json TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS runs_conversation ON runs(requester_id, conversation_id, started_at);
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
    task_id TEXT NOT NULL REFERENCES tasks(id),
    recipient_id TEXT NOT NULL REFERENCES employees(id),
    subject TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE (run_id, task_id)
);
CREATE TABLE IF NOT EXISTS run_steps (
    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
    tool_name TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
    duration_ms REAL NOT NULL, status TEXT NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, requester_id TEXT NOT NULL, filename TEXT NOT NULL,
    format TEXT NOT NULL, model TEXT NOT NULL, raw BLOB NOT NULL,
    status TEXT NOT NULL, chunk_count INTEGER NOT NULL DEFAULT 0,
    error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS document_runbook ON documents(requester_id, filename);
CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
    location TEXT NOT NULL, excerpt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS document_chunk_parent ON document_chunks(document_id);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
    requester_id TEXT NOT NULL, action TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES tasks(id),
    previous_status TEXT NOT NULL, new_status TEXT NOT NULL, status TEXT NOT NULL,
    created_at TEXT NOT NULL, decided_at TEXT, decided_by TEXT
);
"""

TASK_SELECT = """
SELECT t.id, t.title, p.name AS project, e.name AS owner_name,
       t.priority, t.status, t.due_on, t.blocker
FROM tasks t JOIN projects p ON p.id = t.project_id
JOIN employees e ON e.id = t.owner_id
WHERE t.requester_id = ?
"""

DRAFT_SELECT = """
SELECT d.id, d.task_id, e.name AS recipient_name, d.subject, d.body, 'draft' AS status
FROM drafts d JOIN employees e ON e.id = d.recipient_id
WHERE d.run_id = ?
"""

RUN_COLUMNS = "id, conversation_id, requester_id, message, status, started_at, ended_at, error"


class RunInProgress(Exception):
    """The conversation already has an active request."""

class ApprovalConflict(Exception):
    """The decision conflicts with the persisted proposal or task."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = path.resolve()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                yield db
        finally:
            db.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(SCHEMA)

    def is_seeded(self) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM employees WHERE id = ?", (DEMO_USER,)).fetchone() is not None

    def seed(self, today: date | None = None) -> None:
        today = today or datetime.now(UTC).date()
        employees = [
            (DEMO_USER, "Maya Chen"), ("anika-rao", "Anika Rao"),
            ("jordan-lee", "Jordan Lee"), ("sam-rivera", "Sam Rivera"),
        ]
        projects = [("payments", "Payments Migration"), ("platform", "Platform Reliability")]
        tasks = [
            ("PAY-104", "Validate payment rollback", "payments", DEMO_USER, "anika-rao",
             "P0", "in_progress", -4, "The staging replay worker has no test credentials."),
            ("PLAT-201", "Restore alert routing", "platform", DEMO_USER, "jordan-lee",
             "P1", "open", -2, "The on-call webhook is awaiting rotation."),
            ("PAY-106", "Review migration checklist", "payments", DEMO_USER, "sam-rivera",
             "P2", "open", -1, None),
            ("PLAT-205", "Verify retry policy", "platform", DEMO_USER, "jordan-lee",
             "P1", "done", -3, None),
            ("PAY-109", "Rehearse production cutover", "payments", DEMO_USER, "anika-rao",
             "P1", "open", 5, None),
            ("PLAT-210", "Renew a staging certificate", "platform", "sam-rivera", "sam-rivera",
             "P0", "open", -7, "Awaiting an infrastructure handoff."),
        ]
        with self.connect() as db:
            db.executemany("INSERT OR IGNORE INTO employees VALUES (?, ?)", employees)
            db.executemany("INSERT OR IGNORE INTO projects VALUES (?, ?)", projects)
            db.executemany(
                "INSERT OR IGNORE INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ((*row[:7], (today + timedelta(days=row[7])).isoformat(), row[8]) for row in tasks),
            )

    def list_tasks(self, requester_id: str, task_filter: str, today: date) -> list[Task]:
        conditions = {
            "overdue": (" AND t.status <> 'done' AND t.due_on < ?", (today.isoformat(),)),
            "open": (" AND t.status <> 'done'", ()),
            "all": ("", ()),
        }
        suffix, parameters = conditions[task_filter]
        with self.connect() as db:
            rows = db.execute(
                TASK_SELECT + suffix + " ORDER BY t.priority, t.due_on, t.id LIMIT 50",
                (requester_id, *parameters),
            ).fetchall()
        return [Task.model_validate(dict(row)) for row in rows]

    def get_task(self, requester_id: str, task_id: str) -> Task | None:
        with self.connect() as db:
            row = db.execute(TASK_SELECT + " AND t.id = ?", (requester_id, task_id)).fetchone()
        return Task.model_validate(dict(row)) if row else None

    def get_project_status(self, requester_id: str, project: str, today: date) -> ProjectStatus | None:
        with self.connect() as db:
            db.execute("BEGIN")
            row = db.execute(
                """SELECT p.id, p.name FROM projects p JOIN tasks t ON t.project_id = p.id
                WHERE t.requester_id = ? AND (lower(p.id) = lower(?) OR lower(p.name) = lower(?))
                ORDER BY p.id LIMIT 1""",
                (requester_id, project, project),
            ).fetchone()
            if row is None:
                return None
            tasks = [
                Task.model_validate(dict(task))
                for task in db.execute(
                    TASK_SELECT + " AND p.id = ? ORDER BY t.priority, t.due_on, t.id",
                    (requester_id, row["id"]),
                )
            ]
        active = [task for task in tasks if task.status != "done"]
        return ProjectStatus(
            id=row["id"], name=row["name"], total_tasks=len(tasks), open_tasks=len(active),
            completed_tasks=len(tasks) - len(active),
            overdue_tasks=sum(task.due_on < today for task in active),
            blockers=[task for task in active if task.blocker],
        )

    def create_draft(self, requester_id: str, run_id: str, draft: CreateDraft) -> Draft | None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO drafts (id, run_id, task_id, recipient_id, subject, body, created_at)
                SELECT ?, r.id, t.id, t.owner_id, ?, ?, ?
                FROM runs r JOIN tasks t ON t.requester_id = r.requester_id
                WHERE r.id = ? AND r.requester_id = ? AND r.status = 'running'
                    AND t.id = ? AND t.status <> 'done'
                ON CONFLICT (run_id, task_id) DO NOTHING
                """,
                (str(uuid4()), draft.subject, draft.body, utc_now(), run_id, requester_id, draft.task_id),
            )
            row = db.execute(
                DRAFT_SELECT + """AND d.task_id = ? AND EXISTS (
                    SELECT 1 FROM runs r WHERE r.id = d.run_id
                    AND r.requester_id = ? AND r.status = 'running'
                )""",
                (run_id, draft.task_id, requester_id),
            ).fetchone()
        return Draft.model_validate(dict(row)) if row else None

    def start_run(self, requester_id: str, conversation_id: str, message: str) -> str:
        run_id = str(uuid4())
        started = utc_now()
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO runs (id, conversation_id, requester_id, message, status, started_at)
                SELECT ?, ?, ?, ?, 'running', ? WHERE NOT EXISTS (
                    SELECT 1 FROM runs WHERE requester_id = ? AND conversation_id = ?
                    AND status IN ('running', 'awaiting_approval')
                )""",
                (run_id, conversation_id, requester_id, message, started, requester_id, conversation_id),
            )
            if cursor.rowcount != 1:
                raise RunInProgress
        emit("run_started", run_id=run_id, conversation_id=conversation_id, status="running", started_at=started)
        return run_id

    def fail_interrupted_runs(self) -> None:
        ended = utc_now()
        with self.connect() as db:
            interrupted = db.execute(
                """UPDATE runs SET status = 'failed', ended_at = ?,
                error = 'The API restarted before the workflow finished.' WHERE status = 'running'
                RETURNING id, started_at""", (ended,),
            ).fetchall()
            db.execute(
                """UPDATE approvals SET status = 'cancelled', decided_at = ?, decided_by = 'system'
                WHERE status = 'pending' AND EXISTS (
                    SELECT 1 FROM runs WHERE id = approvals.run_id AND status = 'failed'
                )""",
                (utc_now(),),
            )
            db.execute(
                """UPDATE documents SET status = 'failed', error = 'Indexing was interrupted.', updated_at = ?
                WHERE status = 'indexing'""",
                (utc_now(),),
            )
        for row in interrupted:
            emit("run_finished", run_id=row["id"], status="failed", error_code="interrupted",
                 started_at=row["started_at"], ended_at=ended, duration_ms=elapsed_ms(row["started_at"], ended))

    def finish_run(self, run_id: str, result: RunResult | None, error: str | None) -> None:
        ended = utc_now()
        status = "failed" if error else "succeeded"
        with self.connect() as db:
            changed = db.execute(
                """UPDATE runs SET status = ?, ended_at = ?, result_json = ?, error = ?
                WHERE id = ? AND status IN ('running', 'awaiting_approval') RETURNING started_at""",
                (status, ended, result.model_dump_json() if result else None, error, run_id),
            ).fetchone()
            if changed and error:
                db.execute(
                    """UPDATE approvals SET status = 'cancelled', decided_at = ?, decided_by = 'system'
                    WHERE run_id = ? AND status = 'pending'""",
                    (utc_now(), run_id),
                )
        if changed:
            start = changed["started_at"]
            emit("run_finished", run_id=run_id, status=status, started_at=start, ended_at=ended,
                 duration_ms=elapsed_ms(start, ended), **({"error_code": "workflow_failed"} if error else {}))

    def pause_run(self, run_id: str, result: RunResult) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET status = 'awaiting_approval', result_json = ? WHERE id = ? AND status = 'running'",
                (result.model_dump_json(), run_id),
            )
        emit("run_waiting", run_id=run_id, approval_id=str(result.approval_id), status="awaiting_approval")

    def propose_task_update(
        self, requester_id: str, run_id: str, request: ProposeTaskUpdate
    ) -> Approval | None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO approvals
                (id, run_id, requester_id, action, task_id, previous_status, new_status, status, created_at)
                SELECT ?, r.id, r.requester_id, 'task_status_update', t.id, t.status, ?, 'pending', ?
                FROM runs r JOIN tasks t ON t.requester_id = r.requester_id
                WHERE r.id = ? AND r.requester_id = ? AND r.status = 'running' AND t.id = ? AND t.status <> ?
                ON CONFLICT (run_id) DO NOTHING""",
                (str(uuid4()), request.new_status, utc_now(), run_id, requester_id,
                 request.task_id, request.new_status),
            )
            row = db.execute(
                """SELECT * FROM approvals WHERE run_id = ? AND requester_id = ?
                AND task_id = ? AND new_status = ? AND status = 'pending'""",
                (run_id, requester_id, request.task_id, request.new_status),
            ).fetchone()
        return Approval.model_validate(dict(row)) if row else None

    def approvals(self, requester_id: str, *, decided_waiting: bool = False) -> list[Approval]:
        with self.connect() as db:
            where = (" AND r.status = 'awaiting_approval' AND a.status IN ('approved', 'rejected')"
                     if decided_waiting else "")
            rows = db.execute(
                "SELECT a.*, r.status AS run_status FROM approvals a JOIN runs r ON r.id = a.run_id "
                "WHERE a.requester_id = ?" + where + " ORDER BY a.created_at DESC",
                (requester_id,),
            ).fetchall()
        return [Approval.model_validate(dict(row)) for row in rows]

    def get_approval(self, requester_id: str, approval_id: str) -> Approval | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM approvals WHERE requester_id = ? AND id = ?", (requester_id, approval_id)
            ).fetchone()
        return Approval.model_validate(dict(row)) if row else None

    def decide_approval(
        self, requester_id: str, approval_id: str, decision: str, approver_id: str
    ) -> Approval | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM approvals WHERE id = ? AND requester_id = ?", (approval_id, requester_id)
            ).fetchone()
            if row is None:
                return None
            if row["status"] == decision:
                return Approval.model_validate(dict(row))
            if row["status"] != "pending":
                raise ApprovalConflict("This proposal already has a different decision.")
            run = db.execute("SELECT status FROM runs WHERE id = ?", (row["run_id"],)).fetchone()
            if run["status"] != "awaiting_approval":
                raise ApprovalConflict("The workflow is not waiting for this approval.")
            if decision == "approved":
                changed = db.execute(
                    """UPDATE tasks SET status = ? WHERE id = ? AND requester_id = ? AND status = ?""",
                    (row["new_status"], row["task_id"], requester_id, row["previous_status"]),
                )
                if changed.rowcount != 1:
                    raise ApprovalConflict("The task changed since this proposal. Reject it and submit a new request.")
            db.execute(
                """UPDATE approvals SET status = ?, decided_by = ?, decided_at = ?
                WHERE id = ? AND status = 'pending'""",
                (decision, approver_id, utc_now(), approval_id),
            )
            result = db.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        emit("approval_decided", run_id=row["run_id"], approval_id=approval_id, status=decision)
        return Approval.model_validate(dict(result))

    def record_step(
        self, run_id: str, tool_name: str, started_at: str, duration_ms: float, error: str | None
    ) -> None:
        ended = utc_now()
        status = "failed" if error else "succeeded"
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO run_steps
                (run_id, tool_name, started_at, ended_at, duration_ms, status, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run_id, tool_name, started_at, ended, duration_ms, status, error),
            )
        emit("tool_finished", run_id=run_id, step_id=cursor.lastrowid, tool=tool_name, status=status,
             started_at=started_at, ended_at=ended, duration_ms=round(duration_ms, 2),
             **({"error_code": "tool_failed"} if error else {}))

    def history(self, requester_id: str, conversation_id: str) -> list[dict[str, str]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT id, message, result_json FROM runs WHERE requester_id = ?
                AND conversation_id = ? AND status = 'succeeded' ORDER BY started_at DESC LIMIT 4""",
                (requester_id, conversation_id),
            ).fetchall()
            messages = []
            for row in reversed(rows):
                context = json.loads(row["result_json"])
                if context.get("citations"):
                    context["citations"] = [
                        {key: value for key, value in source.items() if key != "excerpt"}
                        for source in context["citations"]
                    ]
                context["drafts"] = self.run_drafts(db, row["id"])
                messages.extend([
                    {"role": "user", "content": row["message"]},
                    {"role": "assistant", "content": json.dumps(context, ensure_ascii=False)},
                ])
        return messages

    @staticmethod
    def run_drafts(db: sqlite3.Connection, run_id: str) -> list[dict]:
        rows = db.execute(DRAFT_SELECT + " ORDER BY d.created_at, d.id", (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_run(self, requester_id: str, run_id: str) -> dict | None:
        with self.connect() as db:
            db.execute("BEGIN")
            row = db.execute(
                "SELECT * FROM runs WHERE id = ? AND requester_id = ?", (run_id, requester_id)
            ).fetchone()
            return self.read_run(db, row) if row is not None else None

    def read_run(self, db: sqlite3.Connection, row: sqlite3.Row) -> dict:
        run = self.with_duration(row)
        run_id = run["id"]
        result = run.pop("result_json")
        run["result"] = json.loads(result) if result else None
        run["drafts"] = self.run_drafts(db, run_id)
        approval = db.execute("SELECT * FROM approvals WHERE run_id = ?", (run_id,)).fetchone()
        run["approval"] = dict(approval) if approval is not None else None
        run["trace"] = [dict(step) for step in db.execute(
            """SELECT id, tool_name, started_at, ended_at, duration_ms, status, error
            FROM run_steps WHERE run_id = ? ORDER BY id""",
            (run_id,),
        )]
        return run

    @staticmethod
    def with_duration(row: sqlite3.Row) -> dict:
        data = dict(row)
        if data["ended_at"]:
            data["duration_ms"] = elapsed_ms(data["started_at"], data["ended_at"])
        return data

    def run_summaries(
        self, requester_id: str, limit: int, status: RunStatus | None = None
    ) -> list[dict]:
        with self.connect() as db:
            return self.read_summaries(db, requester_id, limit, status)

    @staticmethod
    def read_summaries(
        db: sqlite3.Connection, requester_id: str, limit: int, status: RunStatus | None = None
    ) -> list[dict]:
        where = " AND status = ?" if status else ""
        parameters = (requester_id, status, limit) if status else (requester_id, limit)
        rows = db.execute(
            f"SELECT {RUN_COLUMNS} FROM runs WHERE requester_id = ?{where} "
            "ORDER BY started_at DESC, rowid DESC LIMIT ?",
            parameters,
        )
        return [Store.with_duration(row) for row in rows]

    def conversation_summaries(self, requester_id: str, limit: int) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """
                WITH turns AS (
                    SELECT conversation_id AS id, id AS latest_run_id, started_at AS updated_at, status,
                           FIRST_VALUE(message) OVER (
                               PARTITION BY conversation_id ORDER BY started_at, rowid
                           ) AS title,
                           COUNT(*) OVER (PARTITION BY conversation_id) AS run_count,
                           ROW_NUMBER() OVER (
                               PARTITION BY conversation_id ORDER BY started_at DESC, rowid DESC
                           ) AS position
                    FROM runs WHERE requester_id = ?
                )
                SELECT id, latest_run_id, updated_at, status, title, run_count FROM turns
                WHERE position = 1 ORDER BY updated_at DESC, latest_run_id DESC LIMIT ?
                """,
                (requester_id, limit),
            )
            return [dict(row) for row in rows]

    def conversation_runs(self, requester_id: str, conversation_id: str, limit: int) -> list[dict]:
        with self.connect() as db:
            db.execute("BEGIN")
            rows = db.execute(
                """SELECT * FROM runs WHERE requester_id = ? AND conversation_id = ?
                ORDER BY started_at DESC, rowid DESC LIMIT ?""",
                (requester_id, conversation_id, limit),
            ).fetchall()
            return [self.read_run(db, row) for row in reversed(rows)]

    def overview(self, requester_id: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN")
            counts = {"running": 0, "awaiting_approval": 0, "failed": 0, "succeeded": 0}
            counts.update(dict(db.execute(
                "SELECT status, COUNT(*) FROM runs WHERE requester_id = ? GROUP BY status",
                (requester_id,),
            ).fetchall()))
            return {**counts, "total": sum(counts.values()),
                    "recent_runs": self.read_summaries(db, requester_id, 6)}
