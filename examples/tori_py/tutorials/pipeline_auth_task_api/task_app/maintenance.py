"""Maintenance mode: answer every route with 503 before any other stage runs."""

import os
from collections.abc import Awaitable, Callable
from typing import Self

from tori_py import PipelineResult
from tori_py.starlette import RequestContext
from tori_py.starlette.errors import problem_response


class MaintenanceMode:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    @classmethod
    def from_environment(cls) -> Self:
        return cls(os.environ.get("TASK_API_MAINTENANCE") == "on")


class MaintenanceMiddleware:
    def __init__(self, mode: MaintenanceMode) -> None:
        self._mode = mode

    async def handle(
        self,
        context: RequestContext,
        next: Callable[[], Awaitable[PipelineResult]],
    ) -> PipelineResult:
        if not self._mode.enabled:
            return await next()
        return PipelineResult.from_response(
            problem_response(
                503,
                "The Task API is down for maintenance. Try again later.",
                request=context.request,
                headers={"Retry-After": "60"},
            )
        )
