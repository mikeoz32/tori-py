"""Test event stores that reproduce failures a shared database store can report."""

from collections.abc import Sequence
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import uuid4

from tori_py_cqrs_event_sourcing_core import (
    AppendEvent,
    CommitResult,
    EventMetadata,
    EventStoreTransaction,
    IndeterminateCommitError,
    InMemoryEventStore,
    StoredEvent,
    StreamId,
)


class FaultyStore:
    """An in-memory store whose next commit fails in a chosen way."""

    def __init__(self) -> None:
        self.events = InMemoryEventStore()
        self.armed = False

    async def read_stream(
        self,
        stream_id: StreamId,
        *,
        after_version: int = 0,
        limit: int,
    ) -> tuple[StoredEvent, ...]:
        return await self.events.read_stream(
            stream_id, after_version=after_version, limit=limit
        )

    async def read_all(
        self,
        *,
        after_position: int = 0,
        limit: int,
    ) -> tuple[StoredEvent, ...]:
        return await self.events.read_all(after_position=after_position, limit=limit)

    def transaction(self) -> FaultyTransaction:
        return FaultyTransaction(self)

    async def fail_commit(self, transaction: FaultyTransaction) -> CommitResult:
        return await transaction.inner.commit()


class FaultyTransaction:
    def __init__(self, store: FaultyStore) -> None:
        self.store = store
        self.staged: list[tuple[StreamId, int, tuple[AppendEvent, ...]]] = []
        self._context = store.events.transaction()
        self._inner: EventStoreTransaction | None = None

    @property
    def inner(self) -> EventStoreTransaction:
        assert self._inner is not None
        return self._inner

    async def __aenter__(self) -> Self:
        self._inner = await self._context.__aenter__()
        return self

    async def __aexit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._context.__aexit__(error_type, error, traceback)

    async def read_stream(
        self,
        stream_id: StreamId,
        *,
        after_version: int = 0,
        limit: int,
    ) -> tuple[StoredEvent, ...]:
        return await self.inner.read_stream(
            stream_id, after_version=after_version, limit=limit
        )

    def append(
        self,
        stream_id: StreamId,
        *,
        expected_version: int,
        events: Sequence[AppendEvent],
    ) -> None:
        self.inner.append(stream_id, expected_version=expected_version, events=events)
        self.staged.append((stream_id, expected_version, tuple(events)))

    async def commit(self) -> CommitResult:
        if not self.store.armed:
            return await self.inner.commit()
        self.store.armed = False
        return await self.store.fail_commit(self)

    async def rollback(self) -> None:
        await self.inner.rollback()


class CompetingWriterStore(FaultyStore):
    """Another writer commits the same changes first, so this commit conflicts."""

    async def fail_commit(self, transaction: FaultyTransaction) -> CommitResult:
        async with self.events.transaction() as other:
            for stream_id, expected_version, events in transaction.staged:
                other.append(
                    stream_id,
                    expected_version=expected_version,
                    events=[_copy(event) for event in events],
                )
            await other.commit()
        return await transaction.inner.commit()


class LostAcknowledgementStore(FaultyStore):
    """The commit succeeds, but the store cannot tell the application."""

    async def fail_commit(self, transaction: FaultyTransaction) -> CommitResult:
        await transaction.inner.commit()
        raise IndeterminateCommitError("the commit acknowledgement was lost")


def _copy(event: AppendEvent) -> AppendEvent:
    metadata = EventMetadata(event_id=uuid4(), occurred_at=datetime.now(UTC))
    return AppendEvent(event.encoded, metadata)
