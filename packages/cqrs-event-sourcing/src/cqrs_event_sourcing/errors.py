"""Typed event-sourcing failures."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from cqrs_event_sourcing.events import CommitResult, StreamId


class EventSourcingError(Exception):
    """Base class for event-sourcing failures."""


class EventSourcingValidationError(EventSourcingError):
    """Raised when an event-sourcing value violates its contract."""


class InvalidStreamIdError(EventSourcingValidationError):
    """Raised when a stream identifier is not stable and non-empty."""


class InvalidEventMetadataError(EventSourcingValidationError):
    """Raised when event occurrence metadata is invalid."""


class InvalidEventRecordError(EventSourcingValidationError):
    """Raised when an event record is malformed."""


class AggregateError(EventSourcingError):
    """Base class for aggregate failures."""


class AggregateLifecycleError(AggregateError):
    """Raised when an aggregate operation is invalid in its current state."""


class AggregateFaultedError(AggregateLifecycleError):
    """Raised when a faulted aggregate is reused."""


class AggregateEnlistedError(AggregateLifecycleError):
    """Raised when an enlisted aggregate is mutated or enlisted twice."""


class AggregateOwnershipError(AggregateLifecycleError):
    """Raised when a non-owning Unit of Work changes enlistment state."""


class AggregateReplayError(AggregateError):
    """Raised when aggregate history is not one contiguous stream."""


class AggregateStreamMismatchError(AggregateReplayError):
    """Raised when one aggregate is associated with different streams."""

    def __init__(self, *, expected: StreamId, actual: StreamId) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"expected stream {expected!r}, got {actual!r}")


class AggregateTypeMismatchError(AggregateError):
    """Raised when a repository receives another aggregate model."""

    def __init__(self, *, expected: type[object], actual: type[object]) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"expected aggregate type {expected.__qualname__}, "
            f"got {actual.__qualname__}"
        )


class AggregateCommitStateError(AggregateLifecycleError):
    """Raised when a staged aggregate no longer matches its commit plan."""


class SchemaError(EventSourcingError):
    """Base class for event schema and codec failures."""


class SchemaValidationError(SchemaError, EventSourcingValidationError):
    """Raised when a schema declaration or codec result is invalid."""


class DuplicateEventSchemaError(SchemaValidationError):
    """Raised when an alias or event class is registered more than once."""


class UnknownEventSchemaError(SchemaError):
    """Raised when no schema is registered for an event or alias."""


class UnsupportedEventSchemaVersionError(SchemaError):
    """Raised when persisted data uses an unsupported future schema version."""


class EventUpcastError(SchemaError):
    """Raised when an event cannot be advanced to its current schema version."""


class EventCodecError(SchemaError):
    """Raised when event encoding or decoding violates the schema contract."""


class SchemaRegistryFrozenError(SchemaValidationError):
    """Raised when a frozen registry is mutated."""


class SchemaRegistryNotFrozenError(SchemaValidationError):
    """Raised when an unfrozen registry is used for persistence."""


class ResourceLimitError(EventSourcingValidationError):
    """Raised when an event-sourcing resource limit is exceeded."""


class EventStoreError(EventSourcingError):
    """Base class for EventStore failures."""


class ConfirmedCommitError(EventStoreError):
    """Raised when an adapter confirms that commit did not mutate storage."""


class ConfirmedCommitCleanupError(EventSourcingError):
    """Raised when cleanup fails after storage and aggregates committed."""

    def __init__(
        self,
        *,
        result: CommitResult,
        cleanup_error: BaseException,
    ) -> None:
        self.result = result
        self.cleanup_error = cleanup_error
        super().__init__(f"cleanup failed after confirmed commit: {cleanup_error!r}")


class EventStoreTransactionError(EventStoreError):
    """Raised when transaction lifecycle rules are violated."""


class DuplicateStreamAppendError(EventStoreTransactionError):
    """Raised when one transaction stages a stream more than once."""

    def __init__(self, *, stream_id: StreamId) -> None:
        self.stream_id = stream_id
        super().__init__(f"stream {stream_id!r} is already staged")


class OptimisticConcurrencyError(EventStoreError):
    """Raised when a stream's committed version differs from the expected one."""

    def __init__(
        self,
        *,
        stream_id: StreamId,
        expected_version: int,
        actual_version: int,
    ) -> None:
        self.stream_id = stream_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"stream {stream_id!r} expected version {expected_version}, "
            f"got {actual_version}"
        )


class DuplicateEventIdError(EventStoreError):
    """Raised when an event ID is already committed or staged."""

    def __init__(self, *, event_id: UUID) -> None:
        self.event_id = event_id
        super().__init__(f"event ID {event_id} is already present")


class IndeterminateCommitError(EventStoreError):
    """Raised when an adapter cannot prove whether commit succeeded."""


class RepositoryError(EventSourcingError):
    """Base class for repository and Unit of Work failures."""


class AggregateNotFoundError(RepositoryError):
    """Raised when a required aggregate stream does not exist."""


class UnitOfWorkError(RepositoryError):
    """Base class for Unit of Work failures."""


class UnitOfWorkLifecycleError(UnitOfWorkError):
    """Raised when Unit of Work lifecycle rules are violated."""


class DuplicateAggregateSaveError(UnitOfWorkError):
    """Raised when one aggregate is saved twice in a Unit of Work."""


class DuplicateStreamAggregateError(UnitOfWorkError):
    """Raised when two aggregate instances target one enlisted stream."""


class CommitResultMismatchError(UnitOfWorkError):
    """Raised when an EventStore returns a malformed commit result."""


__all__ = [
    "AggregateCommitStateError",
    "AggregateEnlistedError",
    "AggregateError",
    "AggregateFaultedError",
    "AggregateLifecycleError",
    "AggregateNotFoundError",
    "AggregateOwnershipError",
    "AggregateReplayError",
    "AggregateStreamMismatchError",
    "AggregateTypeMismatchError",
    "CommitResultMismatchError",
    "ConfirmedCommitError",
    "ConfirmedCommitCleanupError",
    "DuplicateAggregateSaveError",
    "DuplicateEventIdError",
    "DuplicateEventSchemaError",
    "DuplicateStreamAggregateError",
    "DuplicateStreamAppendError",
    "EventSourcingError",
    "EventSourcingValidationError",
    "EventCodecError",
    "EventStoreError",
    "EventStoreTransactionError",
    "EventUpcastError",
    "IndeterminateCommitError",
    "InvalidEventMetadataError",
    "InvalidEventRecordError",
    "InvalidStreamIdError",
    "OptimisticConcurrencyError",
    "RepositoryError",
    "ResourceLimitError",
    "SchemaError",
    "SchemaRegistryFrozenError",
    "SchemaRegistryNotFrozenError",
    "SchemaValidationError",
    "UnitOfWorkError",
    "UnitOfWorkLifecycleError",
    "UnknownEventSchemaError",
    "UnsupportedEventSchemaVersionError",
]
