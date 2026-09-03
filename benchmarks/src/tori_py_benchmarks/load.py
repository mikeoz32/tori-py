"""Run an isolated Locust process and translate its statistics."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from typing import Any

from tori_py_benchmarks.model import LoadRun


def run_load(
    port: int,
    path: str,
    *,
    concurrency: int,
    duration_seconds: float,
) -> LoadRun:
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    if not math.isfinite(duration_seconds):
        raise ValueError("duration must be finite")
    if duration_seconds <= 0:
        raise ValueError("duration must be positive")
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "tori_py_benchmarks.locust_runner",
            "--host",
            f"http://127.0.0.1:{port}",
            "--users",
            str(concurrency),
            "--duration",
            str(duration_seconds),
        ],
        capture_output=True,
        check=False,
        env={**os.environ, "TORI_PY_BENCHMARK_PATH": path},
        text=True,
        timeout=duration_seconds + 30,
    )
    if process.returncode:
        details = process.stderr.strip() or process.stdout.strip()
        suffix = f": {details}" if details else ""
        raise RuntimeError(f"Locust load process failed{suffix}")
    try:
        stats: dict[str, Any] = json.loads(process.stdout)
        requests = int(stats["num_requests"])
        errors = int(stats["num_failures"])
        latencies = tuple(
            int(milliseconds) * 1_000_000
            for milliseconds, count in stats["response_times"].items()
            for _ in range(int(count))
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("Locust returned invalid statistics") from error
    return LoadRun(
        elapsed_seconds=duration_seconds,
        completed=requests,
        errors=errors,
        latencies_ns=latencies,
    )


__all__ = ["run_load"]
