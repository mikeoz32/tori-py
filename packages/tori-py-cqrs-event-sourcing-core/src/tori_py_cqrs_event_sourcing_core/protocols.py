"""Framework-neutral EventStore protocols."""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from tori_py_cqrs_event_sourcing_core.events import (
    AppendEvent,
    CommitResult,
    StoredEvent,
    StreamId,
)


@runtime_checkable
class EventStoreTransaction(Protocol):
    """One repeatable-read transaction with staged atomic appends."""

    async def read_stream(
        self,
        stream_id: StreamId,
        *,
        after_version: int = 0,
        limit: int,
    ) -> tuple[StoredEvent, ...]:
        """Read one finite stream page from the transaction snapshot."""

    def append(
        self,
        stream_id: StreamId,
        *,
        expected_version: int,
        events: Sequence[AppendEvent],
    ) -> None:
        """Stage the only append batch for one stream."""

    async def commit(self) -> CommitResult:
        """Atomically commit every staged append and return assigned records."""

    async def rollback(self) -> None:
        """Discard staged appends when commit has not succeeded."""


@runtime_checkable
class EventStore(Protocol):
    """Committed event reads and explicit transaction creation."""

    async def read_stream(
        self,
        stream_id: StreamId,
        *,
        after_version: int = 0,
        limit: int,
    ) -> tuple[StoredEvent, ...]:
        """Read one finite stream page from current committed state."""

    async def read_all(
        self,
        *,
        after_position: int = 0,
        limit: int,
    ) -> tuple[StoredEvent, ...]:
        """Read one finite page in global committed order."""

    def transaction(
        self,
    ) -> AbstractAsyncContextManager[EventStoreTransaction]:
        """Create a transaction whose snapshot begins on context entry."""


__all__ = ["EventStore", "EventStoreTransaction"]
