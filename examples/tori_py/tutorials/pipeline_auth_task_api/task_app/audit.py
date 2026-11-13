"""An audit log of write requests and the interceptor that fills it."""

from collections.abc import Awaitable, Callable

import msgspec
from tori_py import ExecutionContext, PipelineResult

from .auth import CurrentPrincipal


class AuditEntry(msgspec.Struct, frozen=True):
    actor: str
    route: str
    outcome: str


class AuditLog:
    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def record(self, entry: AuditEntry) -> None:
        self._entries.append(entry)

    def entries(self) -> list[AuditEntry]:
        return list(self._entries)


class AuditInterceptor:
    """Record who called a route and whether the handler succeeded."""

    def __init__(self, current: CurrentPrincipal, audit: AuditLog) -> None:
        self._current = current
        self._audit = audit

    async def intercept(
        self,
        context: ExecutionContext,
        next: Callable[[], Awaitable[PipelineResult]],
    ) -> PipelineResult:
        outcome = "failed"
        try:
            result = await next()
            outcome = "succeeded"
            return result
        finally:
            self._audit.record(
                AuditEntry(
                    actor=self._current.require().name,
                    route=context.route_id or "unknown",
                    outcome=outcome,
                )
            )
