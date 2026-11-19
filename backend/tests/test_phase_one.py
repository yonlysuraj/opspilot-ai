import asyncio
import json
import sys
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from mcp import Client, StdioServerParameters

from opspilot.config import DEMO_USER, Settings
from opspilot.main import create_app
from opspilot.ollama import Ollama
from opspilot.storage import Store

SCENARIO = "Show my overdue tasks, identify the highest-priority blockers, and draft a follow-up for the responsible team members."


def call(name, **arguments):
    return {"function": {"name": name, "arguments": arguments}}


class ScriptedModel:
    def __init__(self, *replies, blocker_drafts=None, project=None):
        self.replies = iter(replies)
        self.messages = []
        self.blocker_drafts = blocker_drafts
        self.blocker_evidence = []
        self.project = project

    async def chat(self, messages, tools, *, output_schema=None):
        if output_schema:
            if output_schema["title"] == "RequestPlan":
                workflow = "general"
                if self.blocker_drafts is not None:
                    workflow = "overdue_blocker_followups"
                if self.project is not None:
                    workflow = "project_status"
                return {"role": "assistant", "content": json.dumps({"workflow": workflow, "project": self.project})}
            assert output_schema["title"] == "FollowupDrafts"
            self.blocker_evidence = json.loads(messages[-1]["content"])
            return {"role": "assistant", "content": json.dumps({"drafts": self.blocker_drafts})}
        self.messages.append(messages)
        assert {tool["function"]["name"] for tool in tools} == {
            "list_tasks", "get_task_details", "create_followup_draft", "get_project_status", "search_documents",
        }
        reply = next(self.replies)
        if isinstance(reply, str):
            return {"role": "assistant", "content": reply}
        return {"role": "assistant", "content": "", "tool_calls": reply}


@pytest.fixture
def app_settings(tmp_path):
    return Settings(_env_file=None, db_path=tmp_path / "demo.sqlite3")


@pytest.fixture
def seeded_store(app_settings):
    store = Store(app_settings.db_path)
    store.initialize()
    store.seed(today=datetime.now(UTC).date())
    return store


def test_real_mcp_transport_scopes_tasks_and_persists_drafts(tmp_path):
    store = Store(tmp_path / "mcp.sqlite3")
    today = date(2026, 1, 20)
    store.initialize()
    store.seed(today)
    store.seed(today)
    run_id = store.start_run(DEMO_USER, str(uuid4()), SCENARIO)

    async def check():
        parameters = StdioServerParameters(command=sys.executable, args=[
            "-m", "opspilot.mcp_server", "--db", str(store.path), "--requester", DEMO_USER,
            "--run-id", run_id, "--today", today.isoformat(),
        ])
        async with Client(parameters, mode="legacy", read_timeout_seconds=10) as client:
            assert {tool.name for tool in (await client.list_tools()).tools} == {
                "list_tasks", "get_task_details", "create_followup_draft", "get_project_status",
                "search_documents", "propose_task_update",
            }
            listed = await client.call_tool("list_tasks", {"filter": "overdue"})
            assert not listed.is_error
            assert [task["id"] for task in listed.structured_content["tasks"]] == [
                "PAY-104", "PLAT-201", "PAY-106",
            ]
            project = (await client.call_tool("get_project_status", {"project": "Platform Reliability"}))
            assert not project.is_error
            assert project.structured_content["total_tasks"] == 2
            assert project.structured_content["open_tasks"] == 1
            assert project.structured_content["overdue_tasks"] == 1
            assert [task["id"] for task in project.structured_content["blockers"]] == ["PLAT-201"]
            assert (await client.call_tool("get_project_status", {"project": "unknown"})).is_error
            for args in ({"task_id": "PLAT-210"}, {"task_id": "not a task"}):
                assert (await client.call_tool("get_task_details", args)).is_error
            args = {"task_id": "PAY-104", "subject": "Rollback check", "body": "Can you confirm an ETA?"}
            draft = await client.call_tool("create_followup_draft", args)
            replay = await client.call_tool("create_followup_draft", {**args, "subject": "New subject"})
            assert not draft.is_error
            assert draft.structured_content == replay.structured_content
            assert draft.structured_content["recipient_name"] == "Anika Rao"
            assert (await client.call_tool("create_followup_draft", {**args, "task_id": "PLAT-210"})).is_error
            assert (await client.call_tool("create_followup_draft", {**args, "body": "  "})).is_error
            return draft.structured_content["id"]

    draft_id = asyncio.run(check())
    with store.connect() as db:
        rows = db.execute("SELECT id, task_id, recipient_id, subject FROM drafts").fetchall()
    assert [tuple(row) for row in rows] == [(draft_id, "PAY-104", "anika-rao", "Rollback check")]


def test_api_graph_workflow_and_conversation_history(app_settings, seeded_store):
    model = ScriptedModel(
        [call("list_tasks", filter="overdue")],
        [call("get_task_details", task_id="PAY-104"), call("get_task_details", task_id="PLAT-201")],
        [
            call("create_followup_draft", task_id="PAY-104", subject="Rollback blocker",
                 body="Anika, can you confirm a plan to unblock the staging replay worker?"),
            call("create_followup_draft", task_id="PLAT-201", subject="Routing blocker",
                 body="Jordan, when can the on-call webhook be rotated?"),
        ],
        "Saved two follow-up drafts.",
        [call("get_task_details", task_id="PAY-104")],
        "PAY-104 is P0.",
    )
    with TestClient(create_app(app_settings, model)) as api:
        assert api.get("/health/live").json() == {"status": "alive"}
        response = api.post("/api/runs", json={"message": SCENARIO})
        assert response.status_code == 201, response.text
        run = response.json()
        assert run["status"] == "succeeded", run
        assert [x["id"] for x in run["result"]["tasks"]] == ["PAY-104", "PLAT-201", "PAY-106"]
        assert [x["id"] for x in run["result"]["priority_blockers"]] == ["PAY-104", "PLAT-201"]
        assert {x["recipient_name"] for x in run["drafts"]} == {"Anika Rao", "Jordan Lee"}
        assert len(run["trace"]) == 5
        assert all(step["status"] == "succeeded" and step["duration_ms"] >= 0 for step in run["trace"])
        assert api.get(f"/api/runs/{run['id']}").json() == run
        followup = api.post("/api/runs", json={
            "message": "What was the priority of the first blocker?",
            "conversation_id": run["conversation_id"],
        }).json()
        assert followup["status"] == "succeeded", followup
        assert followup["conversation_id"] == run["conversation_id"]
    assert model.messages[4][1]["content"] == SCENARIO
    assert "PAY-104" in model.messages[4][2]["content"]
    with seeded_store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM drafts WHERE run_id = ?", (run["id"],)).fetchone()[0] == 2


@pytest.mark.parametrize("second_task", ["PLAT-201", "PLAT-210"])
def test_blocker_workflow_validates_model_drafts_before_saving(app_settings, seeded_store, second_task):
    model = ScriptedModel(blocker_drafts=[
        {"task_id": "PAY-104", "subject": "Rollback blocker", "body": "Anika, can you confirm an ETA?"},
        {"task_id": second_task, "subject": "Routing blocker", "body": "Jordan, when can we rotate it?"},
    ])
    with TestClient(create_app(app_settings, model)) as api:
        run = api.post("/api/runs", json={"message": SCENARIO}).json()
    assert [task["id"] for task in model.blocker_evidence] == ["PAY-104", "PLAT-201"]
    assert model.blocker_evidence[0]["blocker"] == "The staging replay worker has no test credentials."
    if second_task == "PLAT-201":
        assert run["status"] == "succeeded", run
        assert [task["id"] for task in run["result"]["tasks"]] == ["PAY-104", "PLAT-201", "PAY-106"]
        assert [(draft["task_id"], draft["recipient_name"]) for draft in run["drafts"]] == [
            ("PAY-104", "Anika Rao"), ("PLAT-201", "Jordan Lee"),
        ]
        assert [step["tool_name"] for step in run["trace"]] == [
            "list_tasks", "get_task_details", "get_task_details",
            "create_followup_draft", "create_followup_draft",
        ]
    else:
        assert run["status"] == "failed", run
        assert run["drafts"] == []
        assert len(run["trace"]) == 3
        assert "exactly one draft" in run["error"]


def test_rejected_tool_calls_are_traced_and_do_not_write(app_settings, seeded_store):
    model = ScriptedModel(
        [
            call("send_email", body="Send now"),
            call("list_tasks", filter="overdue", requester_id="sam-rivera"),
            call("create_followup_draft", task_id="PAY-104", subject="Skipped lookup", body="Hello"),
        ],
        "Unable to complete.",
    )
    with TestClient(create_app(app_settings, model)) as api:
        run = api.post("/api/runs", json={"message": "Try unavailable or invalid tools"}).json()
    assert run["status"] == "failed", run
    assert [step["tool_name"] for step in run["trace"]] == [
        "(unavailable)", "list_tasks", "create_followup_draft",
    ]
    assert all(step["status"] == "failed" for step in run["trace"])
    with seeded_store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0


def test_tool_call_budget_stops_a_loop(app_settings, seeded_store):
    settings = app_settings.model_copy(update={"max_tool_calls": 1})
    model = ScriptedModel([call("list_tasks")], [call("list_tasks")])
    with TestClient(create_app(settings, model)) as api:
        run = api.post("/api/runs", json={"message": "List my tasks"}).json()
    assert run["status"] == "failed", run
    assert "budget" in run["error"]
    assert len(run["trace"]) == 1


def test_saved_draft_remains_visible_if_the_run_fails(app_settings, seeded_store):
    model = ScriptedModel(
        [call("get_task_details", task_id="PAY-104")],
        [call("create_followup_draft", task_id="PAY-104", subject="Rollback", body="Can you confirm an ETA?")],
        [call("get_task_details", task_id="PLAT-210")],
        "Unable to complete the additional lookup.",
    )
    with TestClient(create_app(app_settings, model)) as api:
        run = api.post("/api/runs", json={"message": "Draft a follow-up on PAY-104"}).json()
        assert run["status"] == "failed", run
        assert run["result"] is None
        assert [(draft["task_id"], draft["recipient_name"]) for draft in run["drafts"]] == [
            ("PAY-104", "Anika Rao")
        ]
        assert api.get(f"/api/runs/{run['id']}").json() == run


def test_run_timeout_records_failure(app_settings, seeded_store):
    class SlowModel:
        async def chat(self, messages, tools, *, output_schema=None):
            await asyncio.sleep(30)

    settings = app_settings.model_copy(update={"run_timeout_seconds": 4})
    with TestClient(create_app(settings, SlowModel())) as api:
        run = api.post("/api/runs", json={"message": "List my tasks"}).json()
    assert run["status"] == "failed", run
    assert "time limit" in run["error"]
    assert run["ended_at"] is not None


def test_readiness_reports_missing_seed_and_non_tool_model(app_settings, monkeypatch):
    async def show(self, path, payload, timeout):
        assert path == "/api/show"
        return {"capabilities": ["completion"]}

    monkeypatch.setattr(Ollama, "request", show)
    with TestClient(create_app(app_settings)) as api:
        response = api.get("/health/ready")
        assert response.status_code == 503
        assert "opspilot.seed" in response.json()["demo_data"]
        assert "lacks tool calling" in response.json()["ollama"]["detail"]
        assert api.post("/api/runs", json={"message": "List tasks"}).status_code == 503


def test_background_run_and_dashboard_history(app_settings, seeded_store):
    model = ScriptedModel(
        [call("get_project_status", project="payments")], "Payments Migration has overdue work.",
        [call("get_project_status", project="unknown")], "The project could not be found.",
    )
    with TestClient(create_app(app_settings, model)) as api:
        foreign_conversation = str(uuid4())
        foreign_run = seeded_store.start_run("sam-rivera", foreign_conversation, "Private work")
        receipt = api.post("/api/runs?background=true", json={"message": "Check Payments Migration"})
        assert receipt.status_code == 202
        run = receipt.json()
        assert run["status"] == "running"
        assert run["trace"] == []
        ready = api.get(f"/api/runs/{run['id']}").json()
        assert ready["status"] == "succeeded", ready
        assert ready["result"]["projects"][0]["name"] == "Payments Migration"
        assert ready["trace"][0]["tool_name"] == "get_project_status"
        second = api.post("/api/runs?background=true", json={
            "message": "Check the unknown project", "conversation_id": run["conversation_id"],
        }).json()
        conversation_path = f"/api/conversations/{run['conversation_id']}/runs"
        turns = api.get(conversation_path).json()
        assert [(turn["id"], turn["status"]) for turn in turns] == [
            (run["id"], "succeeded"), (second["id"], "failed"),
        ]
        assert turns[1]["trace"][0]["error"]
        conversations = api.get("/api/conversations").json()
        assert [(item["title"], item["run_count"]) for item in conversations] == [("Check Payments Migration", 2)]
        assert [item["id"] for item in api.get("/api/runs?status=failed").json()] == [second["id"]]
        overview = api.get("/api/overview").json()
        assert (overview["total"], overview["succeeded"], overview["failed"], overview["running"]) == (2, 1, 1, 0)
        assert api.get(f"/api/runs/{foreign_run}").status_code == 404
        assert api.get(f"/api/conversations/{foreign_conversation}/runs").status_code == 404
    assert model.messages[2][1]["content"] == "Check Payments Migration"


def test_single_active_run_per_conversation_and_restart_recovery(app_settings, seeded_store):
    conversation = str(uuid4())
    interrupted = seeded_store.start_run(DEMO_USER, conversation, "Interrupted before startup")
    with TestClient(create_app(app_settings)) as api:
        recovered = api.get(f"/api/runs/{interrupted}").json()
        assert recovered["status"] == "failed"
        assert "restarted" in recovered["error"]
        seeded_store.start_run(DEMO_USER, conversation, "Still running")
        duplicate = api.post("/api/runs?background=true", json={"message": "Duplicate", "conversation_id": conversation})
        assert duplicate.status_code == 409
        assert api.get("/api/overview").json()["running"] == 1


@pytest.mark.parametrize("project", ["Payments Migration", "missing-phase-2-demo"])
def test_named_project_workflow_reports_verified_result_or_error(app_settings, seeded_store, project):
    with TestClient(create_app(app_settings, ScriptedModel(project=project))) as api:
        run = api.post("/api/runs", json={"message": f"Show the status of {project}"}).json()
    assert [step["tool_name"] for step in run["trace"]] == ["get_project_status"]
    if project == "Payments Migration":
        assert run["status"] == "succeeded"
        assert run["result"]["projects"][0]["overdue_tasks"] == 2
        assert run["drafts"] == []
    else:
        assert run["status"] == "failed"
        assert run["trace"][0]["error"]
