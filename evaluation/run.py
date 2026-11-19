"""Evaluate the local models through FastAPI and MCP against a disposable demo database."""

import argparse
import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from time import perf_counter

from fastapi.testclient import TestClient
from pydantic import SecretStr

from opspilot.config import DEMO_USER, Settings
from opspilot.main import create_app
from opspilot.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, criterion: str) -> None:
    if not condition:
        raise ValueError(criterion)


def check_decision(api: TestClient, store: Store, run: dict, expected: dict, token: str) -> None:
    proposal = run["approval"]
    task = expected["task"]
    require(bool(proposal) and proposal["task_id"] == task and proposal["status"] == "pending", "pending proposal")
    require(proposal["previous_status"] == expected["before"], "proposal previous status")
    require(proposal["new_status"] == expected["requested"], "proposal requested status")
    require(store.get_task(DEMO_USER, task).status == expected["before"], "task unchanged while pending")
    path = f"/api/approvals/{proposal['id']}/decision"
    request = {"decision": expected["value"]}
    require(api.post(path, json=request).status_code == 401, "unauthorized decision rejected")
    require(store.get_task(DEMO_USER, task).status == expected["before"], "task unchanged after denied request")
    headers = {"Authorization": f"Bearer {token}"}
    first = api.post(path, json=request, headers=headers)
    require(first.status_code == 200, "authorized decision accepted")
    replay = api.post(path, json=request, headers=headers)
    require(replay.status_code == 200 and replay.json() == first.json(), "decision replay idempotent")
    require(store.get_task(DEMO_USER, task).status == expected["after"], "verified task side effect")
    final = api.get(f"/api/runs/{run['id']}").json()
    require(final["status"] == "succeeded" and final["approval"]["status"] == expected["value"],
            "resumed run outcome")


def evaluate_case(api: TestClient, store: Store, case: dict, token: str) -> dict:
    started = perf_counter()
    run = {}
    error = None
    try:
        response = api.post("/api/runs", json={"message": case["prompt"]})
        require(response.status_code == 201, "run accepted")
        run = response.json()
        expected = case["expect"]
        trace = run["trace"]
        info = run["result"] or {}
        require(run["status"] == expected["status"], "run status")
        require([item["tool_name"] for item in trace] == expected["tools"], "recorded MCP tool sequence")
        require([item["status"] for item in trace] == expected.get("tool_statuses", ["succeeded"] * len(trace)),
                "recorded MCP step statuses")
        require([item["task_id"] for item in run["drafts"]] == expected["draft_tasks"], "saved drafts")
        for field, rows, key in (
            ("tasks", info.get("tasks", []), "id"),
            ("blockers", info.get("priority_blockers", []), "id"),
            ("citations", info.get("citations", []), "filename"),
        ):
            if field in expected:
                require([item[key] for item in rows] == expected[field], field)
        for source in info.get("citations", []):
            require(api.get(f"/api/knowledge/sources/{source['id']}").json() == source, "citation resolves")
        if "project" in expected:
            projects = info.get("projects", [])
            require(len(projects) == 1, "one project result")
            require(all(projects[0][key] == value for key, value in expected["project"].items()), "project totals")
        if "answer_contains" in expected:
            require(expected["answer_contains"] in info.get("answer", "").lower(), "answer evidence")
        if "error_contains" in expected:
            require(expected["error_contains"] in (run.get("error") or "").lower(), "sanitized error")
        if "decision" in expected:
            check_decision(api, store, run, expected["decision"], token)
        else:
            require(run["approval"] is None, "no unintended approval")
    except ValueError as exc:
        error = str(exc)
    return {
        "id": case["id"], "passed": error is None, "failed_check": error, "run_id": run.get("id"),
        "duration_ms": round((perf_counter() - started) * 1000, 2),
        "run_status": run.get("status"), "tools": [step["tool_name"] for step in run.get("trace", [])],
    }


def run_evaluation() -> dict:
    cases = json.loads((ROOT / "evaluation" / "cases.json").read_text(encoding="utf-8"))
    base = Settings()
    token = token_urlsafe(32)
    with TemporaryDirectory(prefix="opspilot-eval-", ignore_cleanup_errors=True) as tmp:
        settings = base.model_copy(update={"db_path": Path(tmp) / "eval.sqlite3", "approver_token": SecretStr(token)})
        store = Store(settings.db_path)
        store.initialize()
        store.seed()
        with TestClient(create_app(settings)) as api:
            readiness = api.get("/health/ready")
            if readiness.status_code != 200:
                raise SystemExit(f"Ollama is not ready. {readiness.json()['ollama'].get('detail', '')}")
            results = [evaluate_case(api, store, case, token) for case in cases if case["stage"] == "before_indexing"]
            for path in sorted((ROOT / "data" / "sample_documents").glob("*.txt")):
                response = api.post("/api/knowledge/documents", files={"file": (path.name, path.read_bytes())})
                response.raise_for_status()
                document = response.json()
                if document["status"] != "indexed":
                    raise SystemExit(f"Index setup failed for {path.name}. {document['error']}")
            results.extend(evaluate_case(api, store, case, token) for case in cases if case["stage"] == "indexed")
    return {
        "recorded_at_utc": datetime.now(UTC).isoformat(), "platform": platform.system(),
        "chat_model": base.ollama_model, "embedding_model": base.embedding_model,
        "passed": sum(result["passed"] for result in results), "total": len(results), "cases": results,
        "deterministic_only": [case["id"] for case in cases if case["stage"] == "deterministic"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Optional JSON report path.")
    args = parser.parse_args()
    report = run_evaluation()
    payload = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
    print(payload, end="")
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
