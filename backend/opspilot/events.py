import json
import logging
from datetime import UTC, datetime
from typing import Literal, TypedDict, Unpack

logger = logging.getLogger("opspilot.events")

Event = Literal[
    "run_started", "run_waiting", "run_finished", "tool_finished", "approval_decided",
    "approval_denied", "approval_replay", "approval_resume_failed", "mcp_unavailable",
    "document_indexed", "document_index_failed",
]


class Fields(TypedDict, total=False):
    run_id: str
    conversation_id: str
    step_id: int
    tool: str
    approval_id: str
    document_id: str
    status: str
    error_code: str
    started_at: str
    ended_at: str
    duration_ms: float
    chunk_count: int


def configure_events() -> None:
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)
    logger.propagate = False


def emit(event: Event, **fields: Unpack[Fields]) -> None:
    """Emit operational metadata without request bodies, tool arguments, or error text."""
    payload = {key: fields[key] for key in Fields.__annotations__ if key in fields}
    payload.update(event=event, timestamp=datetime.now(UTC).isoformat())
    logger.info("%s", json.dumps(payload, separators=(",", ":")))


def elapsed_ms(started_at: str, ended_at: str) -> float:
    return round((datetime.fromisoformat(ended_at) - datetime.fromisoformat(started_at)).total_seconds() * 1000, 2)
