# Local benchmark

OpsPilot passed **18 of 18 checks** across six scenarios repeated three times on November 19, 2026. The cited overdue-work scenario took a median of **21.39 seconds**. [Raw trials and model digests](../evaluation/phase5-benchmark.json)

| Scenario | Passed | Median | Observed range |
| --- | ---: | ---: | ---: |
| Empty knowledge base | 3/3 | 5.26 s | 5.13–5.65 s |
| Overdue work with runbook citations and drafts | 3/3 | 21.39 s | 20.61–21.50 s |
| Payments Migration project status | 3/3 | 4.23 s | 4.22–4.44 s |
| Missing project handled as a failed run | 3/3 | 4.48 s | 4.35–4.60 s |
| Authorized approval, decision replay, and task update | 3/3 | 5.25 s | 4.91–5.90 s |
| Rejection with task state preserved | 3/3 | 5.27 s | 5.22–6.21 s |

## Conditions

- Windows 11 build 26300, Intel Core i5-10300H, eight logical processors, and 15.84 GiB usable RAM. Inference ran on CPU with Python 3.12.14 and Ollama 0.35.1.
- Chat used `qwen3:1.7b` in Q4_K_M. Retrieval used `nomic-embed-text`. The benchmark ran sequentially with a fresh demo database for each trial and reused the running Ollama service.
- Timing covered submission through verification via FastAPI’s test client and the real MCP stdio connection. Document indexing before cited cases, browser rendering, human review time, and model download were outside the timed cases. Model residency was left as managed by Ollama.

## Limits and failures

The missing-project case passed when the workflow reported the expected failure. All cases met their criteria in the three trials. An earlier evaluation missed the MCP startup deadline while dependency installs ran. The project now configures the MCP startup and per-tool limits separately.

These results describe a six-scenario synthetic workload on one machine. The deterministic suite separately covers unavailable dependencies, timeouts, and untrusted document instructions. There is no measured throughput or cold-start benchmark in this report.

## Reproduce

With the two models running in Ollama and the locked environment installed, run:

```powershell
uv run --locked --extra test python evaluation/benchmark.py --repeats 3 --device cpu
```

Add `--cpu`, `--memory-gib`, and `--out` to record your machine details or save its report. The benchmark seeds each trial independently and keeps your existing demo database separate. [Case definitions](../evaluation/cases.json)
