from __future__ import annotations

import pytest

from tori_py_benchmarks.model import (
    BenchmarkConfig,
    LoadRun,
    percentile,
    summarize_load_runs,
)


def test_percentile_interpolates_sorted_samples() -> None:
    samples = [4.0, 1.0, 3.0, 2.0]

    assert percentile(samples, 0.0) == 1.0
    assert percentile(samples, 0.5) == 2.5
    assert percentile(samples, 0.95) == pytest.approx(3.85)
    assert percentile(samples, 1.0) == 4.0


def test_percentile_rejects_empty_samples_and_invalid_quantiles() -> None:
    with pytest.raises(ValueError, match="at least one"):
        percentile([], 0.5)
    with pytest.raises(ValueError, match="between zero and one"):
        percentile([1.0], 1.1)


def test_load_summary_reports_distribution_and_aggregate_throughput() -> None:
    runs = [
        LoadRun(elapsed_seconds=2.0, completed=200, errors=0, latencies_ns=(1, 2)),
        LoadRun(elapsed_seconds=2.0, completed=300, errors=1, latencies_ns=(3, 4)),
    ]

    summary = summarize_load_runs(runs)

    assert summary["requests_per_second"] == 125.0
    assert summary["completed"] == 500
    assert summary["errors"] == 1
    assert summary["latency_ms"] == {
        "p50": 2.5e-6,
        "p95": pytest.approx(3.85e-6),
        "p99": pytest.approx(3.97e-6),
    }


def test_load_summary_preserves_all_error_runs() -> None:
    assert summarize_load_runs(
        [LoadRun(elapsed_seconds=1.0, completed=0, errors=3, latencies_ns=())]
    ) == {
        "requests_per_second": 0.0,
        "completed": 0,
        "errors": 3,
        "latency_ms": {"p50": None, "p95": None, "p99": None},
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"duration_seconds": 0},
        {"warmup_seconds": -1},
        {"repeats": 0},
        {"startup_repeats": 0},
        {"concurrencies": ()},
        {"concurrencies": (0,)},
    ],
)
def test_benchmark_config_rejects_non_positive_work(changes: dict[str, object]) -> None:
    values = {
        "duration_seconds": 1.0,
        "warmup_seconds": 0.1,
        "repeats": 1,
        "startup_repeats": 1,
        "concurrencies": (1,),
    }
    values.update(changes)

    with pytest.raises(ValueError):
        BenchmarkConfig(**values)  # type: ignore[arg-type]
