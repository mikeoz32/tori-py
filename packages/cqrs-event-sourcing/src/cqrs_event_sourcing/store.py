"""Atomic in-memory EventStore reference implementation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType, TracebackType
from uuid import UUID

from cqrs_event_sourcing.codec import EventSourcingLimits
from cqrs_event_sourcing.errors import (
    DuplicateEventIdError,
    DuplicateStreamAppendError,
    EventStoreTransactionError,
    OptimisticConcurrencyError,
    ResourceLimitError,
)
from cqrs_event_sourcing.events import (
    AppendEvent,
    CommitResult,
    StoredEvent,
    StreamId,
)


def _position(value: object, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise EventStoreTransactionError(f"{field_name} must be a non-negative integer")
    return value


def _limit(value: object, *, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ResourceLimitError("read limit must be a positive integer")
    if value > maximum:
        raise ResourceLimitError(f"read limit cannot exceed {maximum}")
    return value


class _TransactionState(StrEnum):
    NEW = "new"
    ENTERING = "entering"
    ACTIVE = "active"
    COMMITTING = "committing"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class _StagedAppend:
    stream_id: StreamId
    expected_version: int
    events: tuple[AppendEvent, ...]


@dataclass(frozen=True, slots=True)
class _StoreState:
    streams: Mapping[StreamId, tuple[StoredEvent, ...]]
    events: tuple[StoredEvent, ...]
    event_ids: frozenset[UUID]


class InMemoryEventStore:
    """Process-local semantic reference for EventStore adapter contracts."""

    def __init__(self, *, limits: EventSourcingLimits | None = None) -> None:
        self.limits = limits or EventSourcingLimits()
        self._state = _StoreState(MappingProxyType({}), (), frozenset())
        self._lock = asyncio.Lock()

    async def read_stream(
        self,
        stream_id: StreamId,
        *,
        after_version: int = 0,
        limit: int,
    ) -> tuple[StoredEvent, ...]:
        """Read one page from current committed stream state."""

        self._validate_stream_id(stream_id)
        after = _position(after_version, field_name="after_version")
        page_size = _limit(limit, maximum=self.limits.read_page_size)
        async with self._lock:
            stream = self._state.streams.get(stream_id, ())
            return stream[after : after + page_size]

    async def read_all(
        self,
        *,
        after_position: int = 0,
        limit: int,
    ) -> tuple[StoredEvent, ...]:
        """Read one page from current committed global state."""

        after = _position(after_position, field_name="after_position")
        page_size = _limit(limit, maximum=self.limits.read_page_size)
        async with self._lock:
            return self._state.events[after : after + page_size]

    def transaction(self) -> _InMemoryTransaction:
        """Create an inactive transaction; its snapshot starts on entry."""

        return _InMemoryTransaction(self)

    @staticmethod
    def _validate_stream_id(stream_id: object) -> None:
        if not isinstance(stream_id, StreamId):
            raise EventStoreTransactionError("stream_id must be StreamId")


class _InMemoryTransaction:
    def __init__(self, store: InMemoryEventStore) -> None:
        self._store = store
        self._state = _TransactionState.NEW
        self._snapshot: Mapping[StreamId, tuple[StoredEvent, ...]] = MappingProxyType(
            {}
        )
        self._staged: list[_StagedAppend] = []
        self._staged_streams: set[StreamId] = set()
        self._staged_event_ids: set[UUID] = set()
        self._staged_event_count = 0
        self._staged_bytes = 0

    async def __aenter__(self) -> _InMemoryTransaction:
        if self._state is not _TransactionState.NEW:
            raise EventStoreTransactionError(
                f"cannot enter transaction in {self._state} state"
            )
        self._state = _TransactionState.ENTERING
        try:
            async with self._store._lock:
                self._snapshot = self._store._state.streams
        except BaseException:
            self._state = _TransactionState.ROLLED_BACK
            raise
        self._state = _TransactionState.ACTIVE
        return self

    async def __aexit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del error_type, error, traceback
        if self._state is _TransactionState.ACTIVE:
            await self.rollback()

    async def read_stream(
        self,
        stream_id: StreamId,
        *,
        after_version: int = 0,
        limit: int,
    ) -> tuple[StoredEvent, ...]:
        self._require_active("read")
        self._store._validate_stream_id(stream_id)
        after = _position(after_version, field_name="after_version")
        page_size = _limit(limit, maximum=self._store.limits.read_page_size)
        stream = self._snapshot.get(stream_id, ())
        return stream[after : after + page_size]

    def append(
        self,
        stream_id: StreamId,
        *,
        expected_version: int,
        events: Sequence[AppendEvent],
    ) -> None:
        self._require_active("append")
        self._store._validate_stream_id(stream_id)
        expected = _position(expected_version, field_name="expected_version")
        if stream_id in self._staged_streams:
            raise DuplicateStreamAppendError(stream_id=stream_id)
        batch = tuple(events)
        if not batch:
            raise EventStoreTransactionError("append batch cannot be empty")
        if len(batch) > self._store.limits.max_events_per_append:
            raise ResourceLimitError("append event count limit exceeded")
        if any(not isinstance(event, AppendEvent) for event in batch):
            raise EventStoreTransactionError(
                "append batch must contain AppendEvent values"
            )

        event_ids: list[UUID] = []
        seen_event_ids = set(self._staged_event_ids)
        for event in batch:
            if event.event_id in seen_event_ids:
                raise DuplicateEventIdError(event_id=event.event_id)
            seen_event_ids.add(event.event_id)
            event_ids.append(event.event_id)

        event_count = self._staged_event_count + len(batch)
        if event_count > self._store.limits.max_events_per_transaction:
            raise ResourceLimitError("transaction event count limit exceeded")
        batch_bytes = 0
        for event in batch:
            self._validate_event_limits(event)
            batch_bytes += self._encoded_size(event)
        transaction_bytes = self._staged_bytes + batch_bytes
        if transaction_bytes > self._store.limits.max_transaction_bytes:
            raise ResourceLimitError("transaction byte limit exceeded")

        self._staged.append(_StagedAppend(stream_id, expected, batch))
        self._staged_streams.add(stream_id)
        self._staged_event_ids.update(event_ids)
        self._staged_event_count = event_count
        self._staged_bytes = transaction_bytes

    async def commit(self) -> CommitResult:
        self._require_active("commit")
        self._state = _TransactionState.COMMITTING
        try:
            async with self._store._lock:
                self._validate_commit()
                committed = self._build_committed_events()
                result = CommitResult(committed)
                state = self._build_store_state(committed)
                self._store._state = state
        except BaseException:
            self._state = _TransactionState.ROLLED_BACK
            self._clear_staged()
            raise
        self._state = _TransactionState.COMMITTED
        self._clear_staged()
        return result

    async def rollback(self) -> None:
        if self._state is _TransactionState.ROLLED_BACK:
            return
        if self._state is not _TransactionState.ACTIVE:
            raise EventStoreTransactionError(
                f"cannot rollback transaction in {self._state} state"
            )
        self._state = _TransactionState.ROLLED_BACK
        self._clear_staged()

    def _validate_commit(self) -> None:
        seen = set(self._store._state.event_ids)
        for staged in self._staged:
            actual_version = len(self._store._state.streams.get(staged.stream_id, ()))
            if actual_version != staged.expected_version:
                raise OptimisticConcurrencyError(
                    stream_id=staged.stream_id,
                    expected_version=staged.expected_version,
                    actual_version=actual_version,
                )
            for event in staged.events:
                if event.event_id in seen:
                    raise DuplicateEventIdError(event_id=event.event_id)
                seen.add(event.event_id)

    def _build_committed_events(self) -> tuple[StoredEvent, ...]:
        committed: list[StoredEvent] = []
        global_position = len(self._store._state.events)
        for staged in self._staged:
            for offset, event in enumerate(staged.events, start=1):
                global_position += 1
                committed.append(
                    StoredEvent(
                        stream_id=staged.stream_id,
                        stream_version=staged.expected_version + offset,
                        global_position=global_position,
                        event=event,
                    )
                )
        return tuple(committed)

    def _build_store_state(self, committed: tuple[StoredEvent, ...]) -> _StoreState:
        additions: dict[StreamId, list[StoredEvent]] = {}
        for event in committed:
            additions.setdefault(event.stream_id, []).append(event)
        streams = dict(self._store._state.streams)
        for stream_id, events in additions.items():
            streams[stream_id] = (*streams.get(stream_id, ()), *events)
        all_events = (*self._store._state.events, *committed)
        event_ids = self._store._state.event_ids.union(
            event.event_id for event in committed
        )
        return _StoreState(
            streams=MappingProxyType(streams),
            events=all_events,
            event_ids=frozenset(event_ids),
        )

    def _validate_event_limits(self, event: AppendEvent) -> None:
        limits = self._store.limits
        if len(event.encoded.payload) > limits.max_payload_bytes:
            raise ResourceLimitError("event payload byte limit exceeded")
        headers = event.metadata.headers
        if len(headers) > limits.max_headers:
            raise ResourceLimitError("event header count limit exceeded")
        for name, value in headers.items():
            if len(name.encode()) > limits.max_header_name_bytes:
                raise ResourceLimitError("event header name byte limit exceeded")
            if len(value.encode()) > limits.max_header_value_bytes:
                raise ResourceLimitError("event header value byte limit exceeded")

    @staticmethod
    def _encoded_size(event: AppendEvent) -> int:
        return (
            len(event.encoded.event_type.encode("utf-8"))
            + len(event.encoded.payload)
            + sum(
                len(name.encode("utf-8")) + len(value.encode("utf-8"))
                for name, value in event.metadata.headers.items()
            )
        )

    def _require_active(self, operation: str) -> None:
        if self._state is not _TransactionState.ACTIVE:
            raise EventStoreTransactionError(
                f"cannot {operation} transaction in {self._state} state"
            )

    def _clear_staged(self) -> None:
        self._staged.clear()
        self._staged_streams.clear()
        self._staged_event_ids.clear()
        self._staged_event_count = 0
        self._staged_bytes = 0


__all__ = ["InMemoryEventStore"]
