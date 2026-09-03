"""Command-line orchestration for the Docker benchmark suite."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import pstats
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tori_py_benchmarks.load import run_load
from tori_py_benchmarks.model import (
    BenchmarkConfig,
    LoadRun,
    percentile,
    summarize_load_runs,
)
from tori_py_benchmarks.registry import FRAMEWORKS, SCENARIOS, Framework
from tori_py_benchmarks.report import ComparisonSource, build_comparisons
from tori_py_benchmarks.server import ServerProcess, fetch


def main() -> None:
    arguments = _parse_arguments()
    destination = Path(arguments.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    config = (
        BenchmarkConfig(0.15, 0.05, 1, 1, (1,))
        if arguments.smoke
        else BenchmarkConfig(
            arguments.duration,
            arguments.warmup,
            arguments.repeats,
            arguments.startup_repeats,
            tuple(arguments.concurrency),
        )
    )
    report = (
        execute_profile(
            config,
            scenario=arguments.profile_scenario,
            concurrency=arguments.profile_concurrency,
            profile_path=Path(arguments.profile_output),
        )
        if arguments.profile_output is not None
        else execute(config)
    )
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    _print_summary(report, destination)
    if arguments.profile_output is not None:
        _write_profile_summary(Path(arguments.profile_output))


def execute(config: BenchmarkConfig) -> dict[str, Any]:
    startup_rows = _measure_startup(config)
    http_rows = _measure_http(config)
    comparison_sources: list[ComparisonSource] = [
        {
            "framework": row["framework"],
            "scenario": row["scenario"],
            "concurrency": row["concurrency"],
            "requests_per_second": row["requests_per_second"],
            "latency_ms": row["latency_ms"],
        }
        for row in http_rows
    ]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "metadata": _metadata(),
        "config": {
            "duration_seconds": config.duration_seconds,
            "warmup_seconds": config.warmup_seconds,
            "repeats": config.repeats,
            "startup_repeats": config.startup_repeats,
            "concurrencies": config.concurrencies,
        },
        "startup": startup_rows,
        "http": http_rows,
        "comparisons": build_comparisons(comparison_sources),
    }


def execute_profile(
    config: BenchmarkConfig,
    *,
    scenario: str,
    concurrency: int,
    profile_path: Path,
) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown profile scenario: {scenario}")
    if concurrency <= 0:
        raise ValueError("profile concurrency must be positive")
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    framework = next(item for item in FRAMEWORKS if item.name == "tori-py-asgi")
    with ServerProcess(framework, profile_path=str(profile_path)) as server:
        _verify_contract(framework, server.port)
        if config.warmup_seconds:
            run_load(
                server.port,
                f"/{scenario}",
                concurrency=concurrency,
                duration_seconds=config.warmup_seconds,
            )
        runs = [
            run_load(
                server.port,
                f"/{scenario}",
                concurrency=concurrency,
                duration_seconds=config.duration_seconds,
            )
            for _ in range(config.repeats)
        ]
        summary = summarize_load_runs(runs)
        row = {
            "framework": framework.name,
            "scenario": scenario,
            "concurrency": concurrency,
            **summary,
            "rss_at_end_bytes": server.refresh_rss(),
            "runs": [_serialize_run(run) for run in runs],
        }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "metadata": _metadata(),
        "config": {
            "duration_seconds": config.duration_seconds,
            "warmup_seconds": config.warmup_seconds,
            "repeats": config.repeats,
            "concurrency": concurrency,
        },
        "startup": [],
        "http": [row],
        "comparisons": [],
        "cpu_profile": str(profile_path),
    }


def _measure_startup(config: BenchmarkConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for framework in FRAMEWORKS:
        samples: list[float] = []
        rss_samples: list[int] = []
        for _ in range(config.startup_repeats):
            with ServerProcess(framework) as server:
                samples.append(server.startup_seconds * 1000)
                if server.rss_bytes is not None:
                    rss_samples.append(server.rss_bytes)
        rows.append(
            {
                "framework": framework.name,
                "startup_ms": {
                    "min": min(samples),
                    "p50": percentile(samples, 0.50),
                    "p95": percentile(samples, 0.95),
                    "max": max(samples),
                },
                "rss_at_readiness_bytes_p50": (
                    round(percentile(rss_samples, 0.50)) if rss_samples else None
                ),
                "samples": samples,
            }
        )
    return rows


def _measure_http(config: BenchmarkConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cell_index = 0
    for scenario in SCENARIOS:
        for concurrency in config.concurrencies:
            framework_order = FRAMEWORKS[cell_index:] + FRAMEWORKS[:cell_index]
            cell_index = (cell_index + 1) % len(FRAMEWORKS)
            for framework in framework_order:
                with ServerProcess(framework) as server:
                    _verify_contract(framework, server.port)
                    if config.warmup_seconds:
                        run_load(
                            server.port,
                            f"/{scenario}",
                            concurrency=concurrency,
                            duration_seconds=config.warmup_seconds,
                        )
                    runs = [
                        run_load(
                            server.port,
                            f"/{scenario}",
                            concurrency=concurrency,
                            duration_seconds=config.duration_seconds,
                        )
                        for _ in range(config.repeats)
                    ]
                    summary = summarize_load_runs(runs)
                    rows.append(
                        {
                            "framework": framework.name,
                            "scenario": scenario,
                            "concurrency": concurrency,
                            **summary,
                            "rss_at_end_bytes": server.refresh_rss(),
                            "runs": [_serialize_run(run) for run in runs],
                        }
                    )
    return rows


def _verify_contract(framework: Framework, port: int) -> None:
    for scenario, expected in SCENARIOS.items():
        response = fetch(port, f"/{scenario}")
        if response.status != 200:
            raise RuntimeError(
                f"{framework.name} {scenario} returned HTTP {response.status}"
            )
        actual: object = (
            response.body if isinstance(expected, bytes) else json.loads(response.body)
        )
        if actual != expected:
            raise RuntimeError(
                f"{framework.name} {scenario} contract mismatch: {actual!r}"
            )


def _serialize_run(run: LoadRun) -> dict[str, float | int]:
    return {
        "elapsed_seconds": run.elapsed_seconds,
        "completed": run.completed,
        "errors": run.errors,
        "requests_per_second": run.completed / run.elapsed_seconds,
    }


def _metadata() -> dict[str, Any]:
    versions = {
        framework.name: (
            importlib.metadata.version(framework.distribution)
            if framework.distribution is not None
            else None
        )
        for framework in FRAMEWORKS
    }
    versions["python"] = platform.python_version()
    versions["uvicorn"] = importlib.metadata.version("uvicorn")
    versions["locust"] = importlib.metadata.version("locust")
    benchmark_root = Path(__file__).resolve().parents[2]
    return {
        "versions": versions,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "git_commit": _git_commit(),
        "benchmark_source_sha256": _source_digest(benchmark_root),
        "lock_sha256": _file_digest(benchmark_root / "uv.lock"),
        "base_image": os.environ.get("BENCHMARK_BASE_IMAGE"),
        "resource_limits": {
            "cpu_max": _read_optional("/sys/fs/cgroup/cpu.max"),
            "cpu_quota_us": _read_optional("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"),
            "cpu_period_us": _read_optional("/sys/fs/cgroup/cpu/cpu.cfs_period_us"),
            "cpuset_cpus": _read_optional("/sys/fs/cgroup/cpuset/cpuset.cpus"),
            "memory_max": _read_optional("/sys/fs/cgroup/memory.max"),
            "memory_limit_bytes": _read_optional(
                "/sys/fs/cgroup/memory/memory.limit_in_bytes"
            ),
        },
        "server": "uvicorn --loop asyncio --http httptools --lifespan on",
        "load_generator": "Locust FastHttpUser, isolated local-runner process",
        "load_generator_spawn_rate_per_second": 100,
        "framework_order": "deterministic rotation per scenario/concurrency cell",
    }


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError, subprocess.CalledProcessError:
        return None
    return result.stdout.strip() or None


def _source_digest(benchmark_root: Path) -> str:
    digest = hashlib.sha256()
    for name in ("Dockerfile", "compose.yaml", "pyproject.toml"):
        path = benchmark_root / name
        digest.update(f"benchmarks/{name}\0".encode())
        digest.update(path.read_bytes())
    source_roots = {
        "benchmarks": benchmark_root / "src",
        "tori-py": benchmark_root.parent / "packages" / "tori-py" / "src",
    }
    for label, source_root in source_roots.items():
        for path in sorted(source_root.rglob("*.py")):
            digest.update(
                f"{label}/{path.relative_to(source_root).as_posix()}\0".encode()
            )
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _read_optional(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="ascii").strip()
    except OSError:
        return None


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--warmup", type=float, default=1.0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--startup-repeats", type=int, default=5)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 16, 64])
    parser.add_argument("--output", default="results/latest.json")
    parser.add_argument("--profile-output")
    parser.add_argument("--profile-scenario", choices=SCENARIOS, default="plaintext")
    parser.add_argument("--profile-concurrency", type=int, default=16)
    parser.add_argument("--smoke", action="store_true")
    return parser.parse_args()


def _write_profile_summary(profile_path: Path) -> None:
    stream = io.StringIO()
    stats = pstats.Stats(str(profile_path), stream=stream)
    stats.strip_dirs().sort_stats("cumulative").print_stats(40)
    summary = stream.getvalue()
    summary_path = profile_path.with_suffix(f"{profile_path.suffix}.txt")
    summary_path.write_text(summary, encoding="utf-8")
    print(summary)
    print(f"profile summary: {summary_path}")


def _print_summary(report: dict[str, Any], destination: Path) -> None:
    print("framework scenario concurrency requests/s p95-ms errors")
    for row in report["http"]:
        p95 = row["latency_ms"]["p95"]
        p95_display = f"{p95:.3f}" if p95 is not None else "n/a"
        print(
            f"{row['framework']:<10} {row['scenario']:<9} "
            f"{row['concurrency']:>11} {row['requests_per_second']:>10.1f} "
            f"{p95_display:>7} {row['errors']:>6}"
        )
    print(f"report: {destination}")


if __name__ == "__main__":
    main()
