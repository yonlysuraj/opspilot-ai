"""Verify the Phase 1 scenario against a running, locally seeded API."""

import argparse

import httpx

PROMPT = "Show my overdue tasks, identify the highest-priority blockers, and draft a follow-up for the responsible team members."


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise SystemExit(detail)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=620)
    args = parser.parse_args()
    with httpx.Client(base_url=args.url, timeout=args.timeout, trust_env=False) as client:
        readiness = client.get("/health/ready")
        require(readiness.is_success, f"API is not ready: {readiness.text}")
        response = client.post("/api/runs", json={"message": PROMPT})
        response.raise_for_status()
        run = response.json()
        require(run["status"] == "succeeded",
                f"Run {run['id']} failed: {run['error']}\nTrace: {run['trace']}")
        result = run["result"]
        require([task["id"] for task in result["tasks"]] == ["PAY-104", "PLAT-201", "PAY-106"],
                "The workflow returned unexpected overdue tasks.")
        require({task["id"] for task in result["priority_blockers"]} == {"PAY-104", "PLAT-201"},
                "The workflow returned unexpected blockers.")
        require({(draft["task_id"], draft["recipient_name"]) for draft in run["drafts"]}
                == {("PAY-104", "Anika Rao"), ("PLAT-201", "Jordan Lee")},
                "The workflow did not return both expected follow-up drafts.")
        tools = [step["tool_name"] for step in run["trace"] if step["status"] == "succeeded"]
        require(tools == ["list_tasks", "get_task_details", "get_task_details",
                          "create_followup_draft", "create_followup_draft"],
                "The task-only smoke test recorded an unexpected MCP tool sequence.")
        require(all(step["id"] > 0 and step["duration_ms"] >= 0 for step in run["trace"]),
                "A trace step is missing a persisted ID or measured duration.")
        readback = client.get(f"/api/runs/{run['id']}")
        readback.raise_for_status()
        require(readback.json() == run, "The stored run differs from the original response.")
    print(f"Run {run['id']} passed with {len(run['trace'])} MCP steps.")
    print(result["answer"])
    for draft in run["drafts"]:
        print(f"{draft['task_id']} | {draft['recipient_name']} | {draft['subject']}")


if __name__ == "__main__":
    main()
