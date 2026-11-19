# Local API

The API listens at `http://127.0.0.1:8000` in the default local setup. [OpenAPI UI](http://127.0.0.1:8000/docs)

| Method and path | Purpose |
| --- | --- |
| `GET /health/live` | API process liveness |
| `GET /health/ready` | Seeded demo data and availability of the tool-capable chat model |
| `GET /api/overview` | Run counts and recent activity |
| `GET /api/runs` | Run summaries with optional `limit` and `status` filters |
| `POST /api/runs` | Submit a `message` and optional `conversation_id`. Add `?background=true` to receive an HTTP 202 receipt |
| `GET /api/runs/{run_id}` | Persisted status, result, trace, drafts, and approval |
| `GET /api/conversations` | Recent conversations |
| `GET /api/conversations/{conversation_id}/runs` | Stored turns in chronological order |
| `GET /api/knowledge/documents` | Indexed documents and ingestion status |
| `POST /api/knowledge/documents` | Upload a PDF or TXT as multipart field `file` |
| `POST /api/knowledge/documents/{doc_id}/retry` | Retry a failed index job |
| `POST /api/knowledge/search` | Search passages with `query` and optional `limit` |
| `GET /api/knowledge/sources/{source_id}` | Retrieve the passage associated with a citation |
| `GET /api/approvals` | Pending proposals and decision history |
| `POST /api/approvals/{approval_id}/decision` | Record `approved` or `rejected` using the local approver token |

## Submit and inspect a run

Run these commands in PowerShell from the repository root with the API running.

```powershell
$baseUrl = "http://127.0.0.1:8000"
$run = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/runs" -ContentType "application/json" -Body (
    @{ message = "What is the status of the Payments Migration project?" } | ConvertTo-Json
)
Invoke-RestMethod "$baseUrl/api/runs/$($run.id)"
```

Synchronous submission returns HTTP 201 when the API creates the run. The returned `status` reports the workflow outcome and `error` explains a failure. For asynchronous submission, poll the returned run ID. Reuse `conversation_id` to continue a conversation. A conversation with a running or paused request returns HTTP 409 if another run is submitted.

## Index a runbook and search it

```powershell
curl.exe -F "file=@data/sample_documents/payments-rollback.txt" "$baseUrl/api/knowledge/documents"
Invoke-RestMethod -Method Post -Uri "$baseUrl/api/knowledge/search" -ContentType "application/json" -Body (
    @{ query = "staging rollback test credentials" } | ConvertTo-Json
)
```

Check `status` and `error` on the returned document. Search hits include a source ID, filename, location, and excerpt.

## Review a task status proposal

Submit a run with `message = "Change PAY-109 to in progress."` against fresh demo data. Review the `approval` object before sending a decision. The approval endpoint accepts this request shape.

```http
POST /api/approvals/<approval-id>/decision
Authorization: Bearer <configured-local-approver-token>
Content-Type: application/json

{"decision":"approved"}
```

A missing or invalid token returns HTTP 401 when approval decisions are enabled. A conflicting decision returns HTTP 409. Repeating the same decision returns the original receipt. Read the associated run again to see its resumed outcome.
