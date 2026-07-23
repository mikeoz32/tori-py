"""Example-only identity sequence and erasable content vault."""

import secrets
from types import TracebackType

from cqrs_event_sourcing import EventSourcingUnitOfWork, EventStore
from nestpy import injectable
from starlette.requests import Request

from examples.nestpy.cqrs.event_sourcing.domain.shared import (
    DomainNotFoundError,
    require_text,
)


@injectable()
class IdSequence:
    """Deterministic singleton ID source for the in-process example."""

    def __init__(self) -> None:
        self._next = 1

    def next(self) -> int:
        value = self._next
        self._next += 1
        return value


@injectable()
class ContentVault:
    """Erasable body storage; event streams contain only integer references."""

    def __init__(self) -> None:
        self._next = 1
        self._content: dict[int, str] = {}

    def put(self, body: str) -> int:
        content = require_text(body, field="post body", maximum=10_000)
        reference = self._next
        self._next += 1
        self._content[reference] = content
        return reference

    def get(self, reference: int) -> str:
        try:
            return self._content[reference]
        except KeyError as error:
            raise DomainNotFoundError("post content was erased") from error

    def erase(self, reference: int) -> None:
        self._content.pop(reference, None)


@injectable()
class CredentialStore:
    """Example credential issuer; controllers never trust caller-supplied IDs."""

    def __init__(self) -> None:
        self._principals: dict[str, int] = {}

    def issue(self, member_id: int) -> str:
        token = secrets.token_urlsafe(24)
        self._principals[token] = member_id
        return token

    def authenticate(self, request: Request) -> int | None:
        authorization = request.headers.get("authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.casefold() != "bearer" or not token:
            return None
        return self._principals.get(token)


@injectable()
class PlatformPolicy:
    """Small explicit platform policy used by the suspension command."""

    def can_suspend(self, actor_id: int) -> bool:
        return actor_id == 1


class UnitOfWorkMetrics:
    """Observable proof that each command owns one managed Unit of Work."""

    def __init__(self) -> None:
        self.entries = 0
        self.exits = 0


class ObservedUnitOfWork(EventSourcingUnitOfWork):
    def __init__(self, store: EventStore, metrics: UnitOfWorkMetrics) -> None:
        super().__init__(store)
        self._metrics = metrics

    async def __aenter__(self) -> ObservedUnitOfWork:
        await super().__aenter__()
        self._metrics.entries += 1
        return self

    async def __aexit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            await super().__aexit__(error_type, error, traceback)
        finally:
            self._metrics.exits += 1


__all__ = [
    "ContentVault",
    "CredentialStore",
    "IdSequence",
    "ObservedUnitOfWork",
    "PlatformPolicy",
    "UnitOfWorkMetrics",
]
