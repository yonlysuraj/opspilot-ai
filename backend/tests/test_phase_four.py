import json
import socket
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from mcp import Client, StdioServerParameters

from opspilot import agent
from opspilot.config import Settings
from opspilot.events import logger
from opspilot.knowledge import MAX_UPLOAD
from opspilot.main import create_app
from opspilot.storage import Store


@pytest.fixture
def settings(tmp_path):
    settings = Settings(_env_file=None, db_path=tmp_path / "demo.sqlite3")
    store = Store(settings.db_path)
    store.initialize()
    store.seed()
    return settings


@pytest.mark.parametrize("dependency", ["ollama", "mcp"])
def test_dependency_outage_is_a_safe_failed_run(settings, dependency, monkeypatch):
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        settings = settings.model_copy(
            update={"ollama_url": f"http://127.0.0.1:{unavailable.getsockname()[1]}"}
        )
        if dependency == "mcp":
            def closed_server(*_):
                return Client(StdioServerParameters(
                    command=sys.executable, args=["-c", "raise SystemExit(1)"],
                ), mode="legacy", read_timeout_seconds=5)

            monkeypatch.setattr(agent, "tool_client", closed_server)
        with TestClient(create_app(settings)) as api:
            assert api.get("/health/live").status_code == 200
            assert api.get("/health/ready").status_code == 503
            run = api.post("/api/runs", json={"message": "List my tasks"}).json()
            assert run["status"] == "failed", run
            fragment = "Ollama is unreachable" if dependency == "ollama" else "local MCP server could not"
            assert fragment in run["error"]
            assert run["duration_ms"] >= 0
            assert run["drafts"] == [] and run["approval"] is None


def test_structured_logs_correlate_ids_without_recording_payloads(settings, caplog):
    prompt = "private-user-prompt"
    argument = "private-tool-argument"

    class Model:
        async def chat(self, messages, tools, *, output_schema=None):
            if output_schema:
                return {"role": "assistant", "content": '{"workflow":"general"}'}
            assert "execute_shell" not in {tool["function"]["name"] for tool in tools}
            if messages[-1]["role"] == "user":
                return {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "list_tasks", "arguments": {"filter": "overdue"}}},
                    {"function": {"name": "execute_shell", "arguments": {"command": argument}}},
                ]}
            return {"role": "assistant", "content": "The second tool was unavailable."}

    with TestClient(create_app(settings, Model())) as api:
        logger.addHandler(caplog.handler)
        try:
            run = api.post("/api/runs", json={"message": prompt}).json()
        finally:
            logger.removeHandler(caplog.handler)
    assert run["status"] == "failed", run
    records = [entry.message for entry in caplog.records if entry.name == logger.name]
    events = [json.loads(record) for record in records]
    assert [event["event"] for event in events] == ["run_started", "tool_finished", "tool_finished", "run_finished"]
    assert all(event["run_id"] == run["id"] for event in events)
    assert [event["step_id"] for event in events[1:3]] == [step["id"] for step in run["trace"]]
    assert events[2]["tool"] == "(unavailable)"
    assert events[-1]["duration_ms"] == run["duration_ms"]
    assert not any(secret in record for secret in (prompt, argument, "execute_shell") for record in records)


def test_empty_search_and_oversized_upload(settings):
    with TestClient(create_app(settings)) as api:
        assert api.post("/api/knowledge/search", json={"query": "failover"}).json() == {"items": []}
        large = api.post("/api/knowledge/documents", files={"file": ("too-large.txt", b"x" * (MAX_UPLOAD + 1))})
        assert large.status_code == 413
        def multipart():
            yield b'--test-boundary\r\nContent-Disposition: form-data; name="file"; filename="oversized.txt"\r\n\r\n'
            for _ in range(MAX_UPLOAD // 65536 + 2):
                yield b"x" * 65536
            yield b"\r\n--test-boundary--\r\n"
        streamed = api.post("/api/knowledge/documents", content=multipart(),
                            headers={"Content-Type": "multipart/form-data; boundary=test-boundary"})
        assert streamed.status_code == 413
        assert api.get("/api/knowledge/documents").json() == []
        assert api.get(f"/api/runs/{uuid4()}").status_code == 404
