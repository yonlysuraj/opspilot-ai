# OpsPilot AI implementation planner

Source requirements are in [Full Goal.txt](<Full Goal.txt>). All five phases are implemented and the portfolio workflow has been rehearsed locally.

## Final outcome

A locally runnable enterprise assistant that takes a request from chat, uses a bounded LangGraph workflow to invoke real MCP tools, retrieves cited document context, drafts recommendations and follow-ups, pauses for authorized approval of sensitive changes, and displays the outcome and execution history in a responsive dashboard.

The local MVP uses Python 3.11+, FastAPI, LangGraph, Pydantic, the official MCP Python SDK, SQLite, Ollama, local embeddings, ChromaDB, and React with Vite, TypeScript, and Tailwind CSS. Use LangChain where it helps. The full demo must run on CPU-capable hardware with zero subscription or API cost. Use seeded local enterprise data and keep connector interfaces ready for future GitHub, Jira, and email integrations.

## Phase 1 — Get one real workflow running

**Status.** Complete and verified on Windows with CPU inference.

1. [x] **Checked the development environment.** Used bundled Python 3.12 and Git and verified package installation. Node was available. The shell could not find npm or Docker.
2. [x] **Initialized Git and the backend package.** Added `pyproject.toml`, `.env.example`, and ignore rules for local configuration, the virtual environment, model files, and SQLite files.
3. [x] **Started FastAPI and Ollama.** Added `GET /health/live`, `GET /health/ready`, `POST /api/runs`, and `GET /api/runs/{run_id}`. Readiness checks seeded data and whether the configured model is installed and supports tools.
4. [x] **Created and seeded SQLite.** Added an idempotent seed command for Maya Chen, employees, projects, and tasks. The database also stores drafts, run results, and execution traces.
5. [x] **Connected real MCP tools.** The official MCP SDK runs `list_tasks`, `get_task_details`, and `create_followup_draft` over stdio. Pydantic validates tool inputs, SQLite scopes tasks to the demo requester, and each draft is saved once per task per run.
6. [x] **Built the first LangGraph workflow.** Ollama selects the workflow and writes draft text. The graph retrieves and ranks blockers from MCP data, validates that each selected blocker has one draft, and saves the drafts through MCP. The API returns a structured result and a persisted trace. Model, tool, and run limits bound execution.
7. [x] **Ran automated and live verification.** All nine Pytest cases passed. The live smoke test verified the full workflow through FastAPI and read the stored result back through the API.

### Exit check passed

The request “Show my overdue tasks, identify the highest-priority blockers, and draft a follow-up for the responsible team members” returned three overdue tasks. Five successful MCP calls verified the blockers and saved two unsent drafts in SQLite.

| Task | Priority | Verified blocker | Draft recipient |
| --- | --- | --- | --- |
| `PAY-104` | P0 | The staging replay worker has no test credentials. | Anika Rao |
| `PLAT-201` | P1 | The on-call webhook is awaiting rotation. | Jordan Lee |

Run `956a60af-be2c-49b0-b8b1-8c69abdd3c60` took 17.96 seconds with warm `qwen3:1.7b`. A separate read-only run verified a native model-generated `list_tasks` call.

### Reproduce and continue

Run these checks from the project root with the local API running.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\smoke.py
```

The API uses a single seeded demo identity and saves follow-ups as local drafts. This workspace uses portable Ollama 0.35.1 because the newer build hit a model-cache permissions error. [Setup, restart commands, and code layout](README.md)

Phase 2 begins with the run and conversation API, the React dashboard, and the `get_project_status` MCP tool.

## Phase 2 — Connect the web dashboard

**Status.** Complete and verified with the local browser, FastAPI, SQLite, and Ollama.

8. [x] **Built the run and conversation API.** Added background run receipts, status polling, run summaries, stored conversation turns, and overview counts. A conversation accepts one active run at a time. Added the requester-scoped `get_project_status` MCP tool with counts and blockers from SQLite.
9. [x] **Built the React dashboard.** Added Overview, Agent Workspace, and Workflow Trace using Vite, TypeScript, and Tailwind. The dashboard shows live run status, verified tasks, saved drafts, recorded MCP steps, and failed run details.
10. [x] **Verified the browser workflow.** Submitted the overdue-blocker request from chat, reloaded while it was running, recovered its drafts and trace, and requested Payments Migration status in the same conversation. Verified an unavailable-project error in the failed run trace. Checked desktop and 390-pixel mobile layouts.

**Exit check passed.** Browser run `94366f0c-17f3-4250-aba3-d3bdc53b440c` recorded five MCP calls and two drafts. Follow-up run `fea3ffe3-0fad-402b-a290-9ee20f04bce7` recorded `get_project_status` and reported three open, two overdue, and zero completed Payments Migration tasks. All 13 backend tests and the frontend production build passed. [Dashboard startup and API reference](README.md)

The demo runs in one local API process. Startup marks interrupted active runs as failed and preserves the approval checkpoints added in Phase 3.

## Phase 3 — Add knowledge retrieval and human approval

**Status.** Complete and verified with local Ollama, ChromaDB, SQLite, and the browser.

11. [x] **Indexed PDF and TXT documents.** Added bounded uploads, page or line references, stable document and passage IDs, local Ollama embeddings, a persistent Chroma index, and retryable indexing status.
12. [x] **Retrieved and cited evidence.** Added the `search_documents` MCP tool and Knowledge Base views for upload, search, and passage inspection. Verified that retrieved instructions cannot invoke the proposal tool or bypass approval.
13. [x] **Persisted proposals and paused work.** The `propose_task_update` MCP tool records the exact task and requested status. A LangGraph SQLite checkpoint binds the pending workflow to that proposal. The approval API owns the task mutation.
14. [x] **Enforced authorization and safe resumption.** The API maps a valid approver token to the local approver identity and checks proposal arguments against the checkpoint. SQLite commits the decision and any task change together. The same decision can be retried, and startup resumes recorded decisions if the process stopped before finalizing the run.
15. [x] **Built the dashboard views.** Added Approval Center, decision history, pending counts, clickable citations, paused status, and resumed outcomes in Workspace and Trace.

**Exit check passed.** Browser run `3ae7e930-5ba9-417c-9700-702ca6fefcca` found three overdue tasks, cited two runbooks, and saved two unsent drafts across seven MCP calls. After an API restart, the pending `PAY-109` update still showed its original state. An unauthorized request returned HTTP 401. The authorized decision changed the task once and returned the same receipt on retry. Rejecting `PLAT-201` left it open. All 18 backend tests and the frontend production build passed. [Setup and API reference](README.md)

The local demo uses a single seeded requester and a token-backed approver. PDF indexing requires selectable text.

## Phase 4 — Verify reliability and reproducibility

**Status.** Complete for the local stack. Compose and GitHub Actions configurations passed validation. Container builds and hosted CI await execution on a Docker-capable runner.

16. [x] **Completed observability.** Structured JSON events correlate run IDs, persisted MCP step IDs, timestamps, measured latency, and approval decisions. Events use fixed error codes and omit prompts, tool payloads, document text, and credentials. Run duration includes approval wait time.
17. [x] **Added deterministic and live evaluation.** The evaluation corpus defines expected tools, evidence, and side effects. The live runner uses an isolated seeded database. It passed all six model-backed cases, including an empty knowledge base, cited blockers, a missing project, an approved replay, and rejection. Timeout, dependency outage, and untrusted document checks run in the deterministic suite. [Measured results](evaluation/phase4-results.json)
18. [x] **Locked setup and configured CI.** Added `uv.lock`, Dockerfiles, Compose with persistent model and data volumes, and GitHub Actions for backend tests, frontend builds, and container builds. Installed the backend and frontend dependencies in clean Windows environments and validated the lockfiles, Compose configuration, and Actions workflow. Docker Engine and WSL were unavailable here.
19. [x] **Exercised failure and security boundaries.** Tested Ollama and MCP outages, run timeouts, oversized uploads, empty retrieval, unavailable tools, approval authorization, replay, and restart recovery. Separated the MCP startup timeout from per-tool execution after the first live evaluation hit the startup deadline during dependency installation.

**Exit check passed locally.** All 22 deterministic tests, the clean frontend build, and all six live evaluation cases passed. The live HTTP smoke run `a79d59c1-6f61-43ed-9433-8fee369f9857` recorded five successful MCP steps and two drafts. Its JSON events matched the stored run and step IDs. [Locked setup and verification commands](README.md)

## Phase 5 — Package the portfolio demo

**Status.** Complete for the local portfolio demo.

20. [x] **Wrote the portfolio documentation.** The README covers locked installation, local configuration, startup, model troubleshooting, and the demo. The accompanying docs include a Mermaid architecture diagram, API examples, a five-view walkthrough, and a benchmark report. [README](README.md)
21. [x] **Ran and recorded the benchmark.** The six live scenarios passed across three independent trials on Windows CPU with `qwen3:1.7b` and `nomic-embed-text`. The cited overdue-work scenario had a median of 21.39 seconds. The report records the host, model digests, conditions, per-case ranges, and the earlier startup limitation. [Benchmark report](docs/benchmark.md)
22. [x] **Rehearsed the demo from clean source.** The repository had no initial commit, so the rehearsal used a fresh copy of Git-visible files, new locked backend and frontend installs, a fresh database and approval token, and separate loopback ports. The browser exercised all five views and SQLite confirmed the task outcomes. The publication scan found only the two synthetic runbooks under `data/` and excluded local credentials, databases, model files, and build output.

**Exit check passed.** The clean rehearsal indexed both runbooks, resolved two citations, restored two saved drafts after reload, and showed seven recorded MCP calls. Browser approval changed `PAY-109` to `in_progress`. Browser rejection left `PLAT-201` open. All 22 backend tests and the clean frontend production build passed. The project remains a local Git workspace without a remote. Container builds and hosted CI remain pending verification on a Docker-capable runner.

**Definition of done.** A reviewer can start OpsPilot AI locally, run the overdue-ticket example, inspect actual MCP calls and document citations, verify a persisted follow-up draft, approve or reject a separate proposed update, and replay the history from the dashboard. Setup, tests, and evaluation results are reproducible from the repository.
