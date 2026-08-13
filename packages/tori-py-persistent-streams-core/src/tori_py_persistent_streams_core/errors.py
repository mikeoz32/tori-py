from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from tori_py_persistent_streams_core.models import AvailableBounds, ResumeCursor


class PersistentStreamsError(Exception):
    """Base class for portable persistent-stream failures."""


class ValidationError(PersistentStreamsError, ValueError):
    pass


class ResourceLimitError(ValidationError):
    pass


class UnknownStreamError(PersistentStreamsError, LookupError):
    pass


class IncompatibleStreamError(PersistentStreamsError):
    pass


class InvalidPartitionError(ValidationError):
    pass


class PublishingConflictError(PersistentStreamsError):
    pass


class StalePublishingIdError(PersistentStreamsError):
    pass


class RetentionGapError(PersistentStreamsError):
    def __init__(
        self,
        stream: str,
        partition: int,
        *,
        requested_offset: int | None = None,
        requested_timestamp: datetime | None = None,
        bounds: AvailableBounds | None = None,
        group: str | None = None,
    ) -> None:
        self.stream = stream
        self.partition = partition
        self.requested_offset = requested_offset
        self.requested_timestamp = requested_timestamp
        self.bounds = bounds
        self.group = group
        super().__init__(f"retained history is unavailable for {stream}[{partition}]")


class OwnershipError(PersistentStreamsError):
    pass


class CheckpointError(PersistentStreamsError):
    pass


class CheckpointPersistenceError(CheckpointError):
    def __init__(self, cursor: ResumeCursor | None, cause: BaseException) -> None:
        self.cursor = cursor
        self.cause = cause
        super().__init__(f"checkpoint persistence failed: {cause}")


class CheckpointStrategyError(CheckpointError):
    pass


class LifecycleError(PersistentStreamsError):
    pass


class PoisonRecordError(PersistentStreamsError):
    def __init__(
        self,
        stream: str,
        group: str,
        partition: int,
        offset: int,
        record_id: UUID,
        cause: Exception,
    ) -> None:
        self.stream = stream
        self.group = group
        self.partition = partition
        self.offset = offset
        self.record_id = record_id
        self.cause = cause
        super().__init__(f"record {record_id} at {stream}[{partition}]/{offset} failed")


class AdapterContractError(PersistentStreamsError):
    pass
