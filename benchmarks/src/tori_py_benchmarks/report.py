"""Derived comparisons for machine-readable benchmark reports."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from tori_py_benchmarks.model import LatencySummary


class ComparisonSource(TypedDict):
    framework: str
    scenario: str
    concurrency: int
    requests_per_second: float
    latency_ms: LatencySummary


class Comparison(TypedDict):
    framework: str
    scenario: str
    concurrency: int
    tori_py_rps_difference_percent: float
    tori_py_p95_latency_difference_percent: float | None


def build_comparisons(rows: Sequence[ComparisonSource]) -> list[Comparison]:
    tori_rows = {
        (row["scenario"], row["concurrency"]): row
        for row in rows
        if row["framework"] == "tori-py-asgi"
    }
    comparisons: list[Comparison] = []
    for row in rows:
        if row["framework"] == "tori-py-asgi":
            continue
        key = (row["scenario"], row["concurrency"])
        tori_row = tori_rows.get(key)
        if tori_row is None or row["requests_per_second"] == 0:
            continue
        tori_p95 = tori_row["latency_ms"]["p95"]
        baseline_p95 = row["latency_ms"]["p95"]
        comparisons.append(
            {
                "framework": row["framework"],
                "scenario": row["scenario"],
                "concurrency": row["concurrency"],
                "tori_py_rps_difference_percent": _difference_percent(
                    tori_row["requests_per_second"], row["requests_per_second"]
                ),
                "tori_py_p95_latency_difference_percent": (
                    _difference_percent(tori_p95, baseline_p95)
                    if tori_p95 is not None
                    and baseline_p95 is not None
                    and baseline_p95 != 0
                    else None
                ),
            }
        )
    return comparisons


def _difference_percent(value: float, baseline: float) -> float:
    if baseline == 0:
        raise ValueError("comparison baseline must not be zero")
    return round((value / baseline - 1) * 100, 6)


__all__ = ["Comparison", "ComparisonSource", "build_comparisons"]
