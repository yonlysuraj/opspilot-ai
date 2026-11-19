"""Repeat the live evaluation in fresh subprocesses and summarize case latency."""

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from opspilot.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--cpu", help="Observed CPU model for this benchmark host.")
    parser.add_argument("--memory-gib", type=float, help="Observed usable host memory in GiB.")
    parser.add_argument("--device", choices=("cpu", "gpu", "mixed", "unspecified"), default="unspecified")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    settings = Settings()
    with httpx.Client(base_url=settings.ollama_url, timeout=5, trust_env=False) as api:
        version = api.get("/api/version")
        version.raise_for_status()
        tags = api.get("/api/tags")
        tags.raise_for_status()
    local_models = {row["name"]: row["digest"] for row in tags.json()["models"]}
    model_names = (settings.ollama_model, settings.embedding_model)
    models = {name: local_models.get(name) or local_models.get(f"{name}:latest") for name in model_names}

    trials = []
    runner = Path(__file__).with_name("run.py").resolve()
    with TemporaryDirectory(prefix="opspilot-benchmark-", ignore_cleanup_errors=True) as directory:
        for index in range(1, args.repeats + 1):
            target = Path(directory) / f"trial-{index}.json"
            completed = subprocess.run(
                [sys.executable, str(runner), "--out", str(target)], stdout=subprocess.DEVNULL, check=False,
            )
            if completed.returncode not in (0, 1) or not target.is_file():
                raise SystemExit(f"Trial {index} could not complete. See the evaluation output above.")
            trials.append(json.loads(target.read_text(encoding="utf-8")))

    cases = []
    for item in trials[0]["cases"]:
        measurements = [next(result for result in trial["cases"] if result["id"] == item["id"]) for trial in trials]
        durations = [result["duration_ms"] for result in measurements]
        cases.append({
            "id": item["id"], "passed": sum(result["passed"] for result in measurements),
            "trials": len(measurements), "median_ms": round(statistics.median(durations), 2),
            "min_ms": min(durations), "max_ms": max(durations),
        })
    report = {
        "host": {
            "platform": platform.platform(), "python": platform.python_version(),
            "cpu": args.cpu or platform.processor(), "logical_processors": os.cpu_count(),
            "usable_memory_gib": args.memory_gib, "inference_device": args.device,
        },
        "ollama_version": version.json()["version"],
        "model_digests": models,
        "conditions": "Sequential trials with fresh databases and an already-running local Ollama. "
        "Model residency is not reset between trials. Timings cover API submission through verification of each case.",
        "passed": sum(trial["passed"] for trial in trials),
        "total": sum(trial["total"] for trial in trials),
        "cases": cases,
        "trials": trials,
    }
    payload = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
    print(payload, end="")
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
