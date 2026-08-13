from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from tori_py_persistent_streams_core.checkpoints import (
    CheckpointStore as CheckpointStore,
)
from tori_py_persistent_streams_core.checkpoints import (
    CheckpointStrategy,
    ExternalCheckpointStrategy,
)
from tori_py_persistent_streams_core.models import (
    AppendRequest,
    AvailableBounds,
    CheckpointKey,
    OwnershipToken,
    PublishReceipt,
    RecordPage,
    StartModeCapabilities,
    StoredRecord,
    StreamDefinition,
    Subscription,
)

RecordHandler = Callable[[StoredRecord], Awaitable[None]]


@runtime_checkable
class PartitionLease(Protocol):
    @property
    def key(self) -> CheckpointKey: ...

    @property
    def owner(self) -> OwnershipToken: ...

    @property
    def stopped(self) -> bool: ...

    async def next_record(self) -> StoredRecord | None: ...

    async def checkpoint(self, record: StoredRecord) -> None:
        """Persist progress.

        Cancellation means the persistence outcome is unknown unless this call
        returns or raises a definitive adapter error before cancellation escapes.
        Callers must not assume the record is replayable after cancellation.
        """
        ...

    async def stop(self) -> None: ...

    async def release(self) -> None: ...


@runtime_checkable
class PersistentLog(Protocol):
    @property
    def start_mode_capabilities(self) -> StartModeCapabilities: ...

    async def declare_stream(self, definition: StreamDefinition) -> None: ...

    async def append(self, stream: str, request: AppendRequest) -> PublishReceipt: ...

    async def bounds(self, stream: str, partition: int) -> AvailableBounds | None: ...

    async def read(
        self,
        stream: str,
        partition: int,
        from_offset: int,
        limit: int,
    ) -> RecordPage: ...

    async def acquire(
        self,
        subscription: Subscription,
        partition: int,
        *,
        strategy: CheckpointStrategy | ExternalCheckpointStrategy,
        transfer: bool = False,
    ) -> PartitionLease: ...

    async def close(self) -> None: ...


@runtime_checkable
class PersistentStreamAdapter(PersistentLog, Protocol):
    """Application-owned log with explicit native-intake lifecycle barriers."""

    async def start(self) -> None:
        """Return only when declared intake resources are ready."""
        ...

    async def quiesce(self) -> None:
        """Close native intake admission and cross its callback handoff fence."""
        ...
