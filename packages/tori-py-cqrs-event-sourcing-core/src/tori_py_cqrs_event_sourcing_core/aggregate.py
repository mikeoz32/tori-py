"""Synchronous event-sourced aggregate base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import final
from uuid import uuid4

from tori_py_cqrs_core import Event

from tori_py_cqrs_event_sourcing_core.errors import (
    AggregateCommitStateError,
    AggregateEnlistedError,
    AggregateFaultedError,
    AggregateOwnershipError,
    AggregateReplayError,
    AggregateStreamMismatchError,
)
from tori_py_cqrs_event_sourcing_core.events import (
    EventMetadata,
    PendingEvent,
    RecordedEvent,
    StreamId,
)


@dataclass(frozen=True, slots=True)
class _Enlistment:
    owner: object
    stream_id: StreamId
    events: tuple[PendingEvent, ...]


@dataclass(frozen=True, slots=True)
class _PreparedCommit:
    owner: object
    events: tuple[PendingEvent, ...]
    version: int


class AggregateRoot[IdT](ABC):
    """Record domain events and rebuild state from one committed stream."""

    def __init__(self, aggregate_id: IdT) -> None:
        self._id = aggregate_id
        self._version = 0
        self._stream_id: StreamId | None = None
        self._pending_events: list[PendingEvent] = []
        self._faulted = False
        self._enlistment: _Enlistment | None = None
        self._prepared_commit: _PreparedCommit | None = None

    @property
    @final
    def id(self) -> IdT:
        """Return the application-defined aggregate identifier."""

        return self._id

    @property
    @final
    def version(self) -> int:
        """Return the last confirmed committed stream version."""

        return self._version

    @property
    @final
    def pending_events(self) -> tuple[PendingEvent, ...]:
        """Return an immutable snapshot of uncommitted events."""

        return tuple(self._pending_events)

    @property
    @final
    def is_faulted(self) -> bool:
        """Return whether failed event application made this instance unusable."""

        return self._faulted

    @property
    @final
    def is_enlisted(self) -> bool:
        """Return whether a Unit of Work currently owns this aggregate."""

        return self._enlistment is not None

    @final
    def raise_event(
        self,
        event: Event,
        *,
        metadata: EventMetadata | None = None,
    ) -> None:
        """Apply and record one new domain event."""

        self._require_mutable()
        pending = PendingEvent(
            event=event,
            metadata=metadata
            if metadata is not None
            else EventMetadata(event_id=uuid4(), occurred_at=datetime.now(UTC)),
        )
        try:
            self._apply(pending.event)
        except BaseException:
            self._faulted = True
            raise
        self._pending_events.append(pending)

    @final
    def _replay(self, events: Iterable[RecordedEvent]) -> None:
        """Apply one finite, contiguous page of committed events."""

        self._require_mutable()
        if self._pending_events:
            raise AggregateReplayError("cannot replay with pending events")
        try:
            page = tuple(events)
            if any(not isinstance(record, RecordedEvent) for record in page):
                raise AggregateReplayError(
                    "replay page must contain RecordedEvent values"
                )
            if not page:
                return
            expected_stream = self._stream_id or page[0].stream_id
            expected_version = self._version + 1
            for record in page:
                if record.stream_id != expected_stream:
                    raise AggregateStreamMismatchError(
                        expected=expected_stream,
                        actual=record.stream_id,
                    )
                if record.stream_version != expected_version:
                    raise AggregateReplayError(
                        f"expected stream version {expected_version}, "
                        f"got {record.stream_version}"
                    )
                expected_version += 1
        except BaseException:
            self._faulted = True
            raise

        self._stream_id = expected_stream
        for record in page:
            try:
                self._apply(record.event)
            except BaseException:
                self._faulted = True
                raise
            self._version = record.stream_version

    @final
    def _enlist(
        self,
        owner: object,
        *,
        stream_id: StreamId,
        events: Sequence[PendingEvent],
    ) -> None:
        """Seal this aggregate under one Unit of Work owner token."""

        self._require_mutable()
        if self._enlistment is not None:
            raise AggregateEnlistedError("aggregate is already enlisted")
        snapshot = tuple(events)
        if not snapshot or snapshot != tuple(self._pending_events):
            raise AggregateCommitStateError(
                "enlistment must contain the complete pending event snapshot"
            )
        if self._stream_id is not None and self._stream_id != stream_id:
            raise AggregateStreamMismatchError(
                expected=self._stream_id,
                actual=stream_id,
            )
        self._stream_id = stream_id
        self._enlistment = _Enlistment(owner, stream_id, snapshot)
        self._prepared_commit = None

    @final
    def _prepare_commit(
        self,
        owner: object,
        *,
        events: Sequence[PendingEvent],
        version: int,
    ) -> _PreparedCommit:
        """Validate the local transition before storage commit starts."""

        enlistment = self._owned_enlistment(owner)
        snapshot = tuple(events)
        if snapshot != enlistment.events or snapshot != tuple(self._pending_events):
            raise AggregateCommitStateError("pending events changed after enlistment")
        if version != self._version + len(snapshot):
            raise AggregateCommitStateError(
                f"committed version must be {self._version + len(snapshot)}, "
                f"got {version}"
            )
        prepared = _PreparedCommit(owner, snapshot, version)
        self._prepared_commit = prepared
        return prepared

    @final
    def _mark_committed(self, prepared: object) -> None:
        """Perform the prevalidated non-failing local commit transition."""

        if self._prepared_commit is not prepared:
            raise AggregateCommitStateError("commit transition was not prepared")
        assert isinstance(prepared, _PreparedCommit)
        self._version = prepared.version
        self._pending_events.clear()
        self._enlistment = None
        self._prepared_commit = None

    @final
    def _release(self, owner: object) -> None:
        """Release confirmed rolled-back work while retaining pending events."""

        self._owned_enlistment(owner)
        self._enlistment = None
        self._prepared_commit = None

    @final
    def _fault(self, owner: object) -> None:
        """Make an ambiguously committed or stale aggregate unusable."""

        self._owned_enlistment(owner)
        self._faulted = True
        self._enlistment = None
        self._prepared_commit = None

    @final
    def _validate_staging(self, *, stream_id: StreamId) -> None:
        """Reject lifecycle and stream mismatches before serialization."""

        self._require_mutable()
        if self._stream_id is not None and self._stream_id != stream_id:
            raise AggregateStreamMismatchError(
                expected=self._stream_id,
                actual=stream_id,
            )

    @final
    def _owned_enlistment(self, owner: object) -> _Enlistment:
        if self._enlistment is None:
            raise AggregateOwnershipError("aggregate is not enlisted")
        if self._enlistment.owner is not owner:
            raise AggregateOwnershipError("aggregate belongs to another Unit of Work")
        return self._enlistment

    @final
    def _require_mutable(self) -> None:
        if self._faulted:
            raise AggregateFaultedError("aggregate is faulted and must be reloaded")
        if self._enlistment is not None:
            raise AggregateEnlistedError("aggregate is enlisted and cannot be mutated")

    @abstractmethod
    def _apply(self, event: Event) -> None:
        """Apply one domain event without I/O or external side effects."""


__all__ = ["AggregateRoot"]
