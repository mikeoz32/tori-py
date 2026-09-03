"""Validated benchmark configuration and result aggregation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypedDict


class LatencySummary(TypedDict):
    p50: float | None
    p95: float | None
    p99: float | None


class LoadSummary(TypedDict):
    requests_per_second: float
    completed: int
    errors: int
    latency_ms: LatencySummary


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    duration_seconds: float
    warmup_seconds: float
    repeats: int
    startup_repeats: int
    concurrencies: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.duration_seconds <= 0:
            raise ValueError("duration must be positive")
        if self.warmup_seconds < 0:
            raise ValueError("warmup must not be negative")
        if self.repeats <= 0:
            raise ValueError("repeats must be positive")
        if self.startup_repeats <= 0:
            raise ValueError("startup repeats must be positive")
        if not self.concurrencies or any(value <= 0 for value in self.concurrencies):
            raise ValueError("concurrencies must contain positive integers")


@dataclass(frozen=True, slots=True)
class LoadRun:
    elapsed_seconds: float
    completed: int
    errors: int
    latencies_ns: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.elapsed_seconds <= 0:
            raise ValueError("elapsed time must be positive")
        if self.completed < 0 or self.errors < 0:
            raise ValueError("request counts must not be negative")
        if self.completed and not self.latencies_ns:
            raise ValueError("completed requests require latency samples")


def percentile(samples: Sequence[int | float], quantile: float) -> float:
    """Return a linearly interpolated percentile."""
    if not samples:
        raise ValueError("percentile requires at least one sample")
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between zero and one")
    ordered = sorted(samples)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def summarize_load_runs(runs: list[LoadRun]) -> LoadSummary:
    if not runs:
        raise ValueError("load summary requires at least one run")
    latencies = tuple(latency for run in runs for latency in run.latencies_ns)
    completed = sum(run.completed for run in runs)
    elapsed = sum(run.elapsed_seconds for run in runs)
    latency_summary: LatencySummary = (
        {
            "p50": percentile(latencies, 0.50) / 1_000_000,
            "p95": percentile(latencies, 0.95) / 1_000_000,
            "p99": percentile(latencies, 0.99) / 1_000_000,
        }
        if latencies
        else {"p50": None, "p95": None, "p99": None}
    )
    return {
        "requests_per_second": completed / elapsed,
        "completed": completed,
        "errors": sum(run.errors for run in runs),
        "latency_ms": latency_summary,
    }


__all__ = [
    "BenchmarkConfig",
    "LatencySummary",
    "LoadRun",
    "LoadSummary",
    "percentile",
    "summarize_load_runs",
]
