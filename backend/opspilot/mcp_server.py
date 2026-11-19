import argparse
import logging
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from .config import Settings
from .models import (
    Approval, CreateDraft, Draft, DraftBody, DraftSubject, GetProject, GetTask, ListTasks, Message,
    ProjectKey, ProjectStatus, ProposeTaskUpdate, SearchDocuments, SearchResults, Task, TaskId, TaskList,
    TaskStatus,
)
from .storage import Store


def build_server(store: Store, requester_id: str, run_id: str, today: date, settings: Settings) -> MCPServer:
    server = MCPServer("OpsPilot demo tasks")

    @server.tool()
    def list_tasks(filter: Literal["overdue", "open", "all"] = "overdue") -> TaskList:
        """List the current requester's tasks. Use overdue, open, or all as the filter."""
        args = ListTasks(filter=filter)
        return TaskList(tasks=store.list_tasks(requester_id, args.filter, today))

    @server.tool()
    def get_task_details(task_id: TaskId) -> Task:
        """Read the priority, blocker, and responsible owner for a task ID."""
        args = GetTask(task_id=task_id)
        task = store.get_task(requester_id, args.task_id)
        if task is None:
            raise ToolError("Task is unavailable to this requester.")
        return task

    @server.tool()
    def get_project_status(project: ProjectKey) -> ProjectStatus:
        """Summarize the requester's open, completed, overdue, and blocked work for a project.

        Pass its ID (payments or platform) or display name (Payments Migration or Platform Reliability).
        """
        args = GetProject(project=project)
        status = store.get_project_status(requester_id, args.project, today)
        if status is None:
            raise ToolError("Project is unavailable to this requester.")
        return status

    @server.tool()
    def create_followup_draft(task_id: TaskId, subject: DraftSubject, body: DraftBody) -> Draft:
        """Save an unsent draft for the task's responsible owner. Pass the message text."""
        args = CreateDraft(task_id=task_id, subject=subject, body=body)
        draft = store.create_draft(requester_id, run_id, args)
        if draft is None:
            raise ToolError("This task cannot be drafted for in the current run.")
        return draft

    @server.tool()
    def search_documents(
        query: Annotated[Message, Field(max_length=500)], limit: Annotated[int, Field(ge=1, le=5)] = 3
    ) -> SearchResults:
        """Find relevant passages in the requester's indexed PDF and TXT documents."""
        from .knowledge import Knowledge, KnowledgeError

        request = SearchDocuments(query=query, limit=limit)
        try:
            return Knowledge(settings, store).search(requester_id, request.query, request.limit)
        except KnowledgeError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    def propose_task_update(task_id: TaskId, new_status: TaskStatus) -> Approval:
        """Store a proposal for a task status update. A separate approval is required to apply it."""
        proposal = store.propose_task_update(requester_id, run_id, ProposeTaskUpdate(task_id=task_id, new_status=new_status))
        if proposal is None:
            raise ToolError("Task is unavailable, already at the requested status, or has a different proposal.")
        return proposal

    return server


def main() -> None:
    # The API records sanitized tool outcomes. SDK and dependency logs in the
    # subprocess can otherwise include raw validation inputs and tool payloads.
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description="Run the OpsPilot MCP server on stdio.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--requester", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--today", required=True, type=date.fromisoformat)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--embedding-model", default="nomic-embed-text")
    args = parser.parse_args()
    settings = Settings(
        _env_file=None, db_path=args.db, ollama_url=args.ollama_url, embedding_model=args.embedding_model,
    )
    build_server(Store(args.db), args.requester, args.run_id, args.today, settings).run(transport="stdio")


if __name__ == "__main__":
    main()
