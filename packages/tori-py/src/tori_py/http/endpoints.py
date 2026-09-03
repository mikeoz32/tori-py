"""Adapter-bound HTTP endpoint execution plans."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from tori_py.http.routes import RoutePlan


@dataclass(frozen=True, slots=True)
class CompiledEndpoint[ResponseT]:
    """A route plan with its adapter-specific execution path selected."""

    plan: RoutePlan
    execute: Callable[..., Awaitable[ResponseT]]


__all__ = ["CompiledEndpoint"]
