from __future__ import annotations

from tori_py_benchmarks.report import ComparisonSource, build_comparisons


def test_comparisons_express_tori_py_difference_from_each_baseline() -> None:
    rows: list[ComparisonSource] = [
        {
            "framework": "raw-asgi",
            "scenario": "json",
            "concurrency": 16,
            "requests_per_second": 200.0,
            "latency_ms": {"p50": 0.5, "p95": 1.0, "p99": 1.5},
        },
        {
            "framework": "tori-py-starlette",
            "scenario": "json",
            "concurrency": 16,
            "requests_per_second": 80.0,
            "latency_ms": {"p50": 1.2, "p95": 2.5, "p99": 3.5},
        },
        {
            "framework": "tori-py-asgi",
            "scenario": "json",
            "concurrency": 16,
            "requests_per_second": 100.0,
            "latency_ms": {"p50": 1.0, "p95": 2.0, "p99": 3.0},
        },
    ]

    assert build_comparisons(rows) == [
        {
            "framework": "raw-asgi",
            "scenario": "json",
            "concurrency": 16,
            "tori_py_rps_difference_percent": -50.0,
            "tori_py_p95_latency_difference_percent": 100.0,
        },
        {
            "framework": "tori-py-starlette",
            "scenario": "json",
            "concurrency": 16,
            "tori_py_rps_difference_percent": 25.0,
            "tori_py_p95_latency_difference_percent": -20.0,
        },
    ]
