from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import islice

from tori_py_persistent_streams_core.checkpoints import (
    CheckpointStore,
    CheckpointStrategy,
    ExternalCheckpointStrategy,
    validate_checkpoint_store_call,
)
from tori_py_persistent_streams_core.errors import (
    AdapterContractError,
    CheckpointError,
    CheckpointPersistenceError,
    CheckpointStrategyError,
    IncompatibleStreamError,
    InvalidPartitionError,
    LifecycleError,
    OwnershipError,
    PublishingConflictError,
    ResourceLimitError,
    RetentionGapError,
    StalePublishingIdError,
    UnknownStreamError,
    ValidationError,
)
from tori_py_persistent_streams_core.models import (
    AppendRequest,
    AvailableBounds,
    Beginning,
    CheckpointKey,
    CursorKind,
    End,
    ExactOffset,
    OwnershipToken,
    PublishOutcome,
    PublishReceipt,
    RecordPage,
    RelativeTime,
    ResumeCursor,
    StartModeCapabilities,
    StartPosition,
    StoredRecord,
    StreamDefinition,
    Subscription,
    Timestamp,
)
from tori_py_persistent_streams_core.validation import validate_append_request_limits


@dataclass(slots=True)
class _PartitionState:
    records: list[StoredRecord] = field(default_factory=list)
    next_offset: int = 0
    earliest_offset: int = 0
    last_timestamp: datetime | None = None
    removed_through: datetime | None = None


@dataclass(slots=True)
class _ProducerState:
    publishing_id: int
    request: AppendRequest
    receipt: PublishReceipt


@dataclass(slots=True)
class _StreamState:
    definition: StreamDefinition
    partitions: list[_PartitionState]
    producers: dict[tuple[int, str], _ProducerState] = field(default_factory=dict)


@dataclass(frozen=True, slots=True, eq=False)
class _StrategyBinding:
    mode: str
    identity: str | None = None
    store: CheckpointStore | None = None

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _StrategyBinding)
            and self.mode == other.mode
            and self.identity == other.identity
            and self.store is other.store
        )


class InMemoryPersistentLog:
    """Serialized, non-durable semantic reference implementation."""

    start_mode_capabilities = StartModeCapabilities(True, True, True, True, True)

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        max_active_leases: int = 4096,
    ) -> None:
        if (
            isinstance(max_active_leases, bool)
            or not isinstance(max_active_leases, int)
            or max_active_leases <= 0
        ):
            raise ValidationError("max_active_leases must be positive")
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_active_leases = max_active_leases
        self._lock = asyncio.Lock()
        self._streams: dict[str, _StreamState] = {}
        self._owners: dict[CheckpointKey, OwnershipToken] = {}
        self._leases: dict[CheckpointKey, InMemoryPartitionLease] = {}
        self._transfers: dict[CheckpointKey, object] = {}
        self._generations: dict[CheckpointKey, int] = {}
        self._broker_cursors: dict[CheckpointKey, ResumeCursor] = {}
        self._group_strategies: dict[tuple[str, str], _StrategyBinding] = {}
        self._pending_group_strategies: dict[
            tuple[str, str], tuple[_StrategyBinding, int]
        ] = {}
        self._closed = False
        self._started = False
        self._quiescing = False

    async def start(self) -> None:
        async with self._lock:
            self._require_open()
            self._started = True
            self._quiescing = False

    async def quiesce(self) -> None:
        async with self._lock:
            self._quiescing = True

    async def declare_stream(self, definition: StreamDefinition) -> None:
        snapshot = StreamDefinition(
            definition.name,
            definition.partition_count,
            definition.limits,
            definition.router,
        )
        async with self._lock:
            self._require_open()
            current = self._streams.get(snapshot.name)
            if current is not None:
                if current.definition.compatibility_key != snapshot.compatibility_key:
                    raise IncompatibleStreamError(snapshot.name)
                return
            self._streams[snapshot.name] = _StreamState(
                snapshot,
                [_PartitionState() for _ in range(snapshot.partition_count)],
            )

    async def append(self, stream: str, request: AppendRequest) -> PublishReceipt:
        async with self._lock:
            self._require_open()
            state = self._stream(stream)
            validate_append_request_limits(state.definition, request)
            partition = state.definition.router.route(
                bytes(request.partition_key), state.definition.partition_count
            )
            if (
                isinstance(partition, bool)
                or not isinstance(partition, int)
                or partition < 0
                or partition >= state.definition.partition_count
            ):
                raise InvalidPartitionError("router returned an invalid partition")
            producer_key = (
                None
                if request.producer_name is None
                else (partition, request.producer_name)
            )
            if producer_key is not None:
                existing = state.producers.get(producer_key)
                if existing is not None:
                    assert request.publishing_id is not None
                    if request.publishing_id == existing.publishing_id:
                        if request != existing.request:
                            raise PublishingConflictError(
                                "publishing ID request differs"
                            )
                        return PublishReceipt(
                            existing.receipt.record_id,
                            partition,
                            PublishOutcome.DEDUPLICATED,
                            existing.receipt.confirmation_facts,
                        )
                    if request.publishing_id < existing.publishing_id:
                        raise StalePublishingIdError("publishing ID is stale")
            partition_state = state.partitions[partition]
            appended_at = self._now()
            if (
                partition_state.last_timestamp is not None
                and appended_at < partition_state.last_timestamp
            ):
                appended_at = partition_state.last_timestamp
            offset = partition_state.next_offset
            partition_state.next_offset += 2
            record = StoredRecord(
                request.record_id,
                stream,
                bytes(request.partition_key),
                bytes(request.payload),
                {name: bytes(value) for name, value in request.headers.items()},
                partition,
                offset,
                appended_at,
            )
            partition_state.records.append(record)
            partition_state.last_timestamp = appended_at
            receipt = PublishReceipt(
                request.record_id,
                partition,
                PublishOutcome.CONFIRMED,
                ("in-memory-accepted",),
            )
            if producer_key is not None:
                assert request.publishing_id is not None
                state.producers[producer_key] = _ProducerState(
                    request.publishing_id, request, receipt
                )
            return receipt

    async def bounds(self, stream: str, partition: int) -> AvailableBounds:
        async with self._lock:
            self._require_open()
            state = self._stream(stream)
            part = self._partition(state, partition)
            return self._bounds(part)

    async def read(
        self,
        stream: str,
        partition: int,
        from_offset: int,
        limit: int,
    ) -> RecordPage:
        async with self._lock:
            self._require_open()
            state = self._stream(stream)
            part = self._partition(state, partition)
            self._validate_read(state.definition, from_offset, limit)
            self._require_retained(stream, partition, from_offset, part)
            matching = (
                record for record in part.records if record.offset >= from_offset
            )
            records = tuple(islice(matching, limit))
            return RecordPage(records, self._bounds(part))

    async def acquire(
        self,
        subscription: Subscription,
        partition: int,
        *,
        strategy: CheckpointStrategy | ExternalCheckpointStrategy,
        transfer: bool = False,
    ) -> InMemoryPartitionLease:
        store: CheckpointStore | None
        binding: _StrategyBinding
        if strategy is CheckpointStrategy.BROKER_MANAGED:
            store = None
            binding = _StrategyBinding(strategy.value)
        elif isinstance(strategy, ExternalCheckpointStrategy):
            store = strategy.store
            binding = _StrategyBinding("external", strategy.identity, store)
        else:
            raise CheckpointStrategyError("unsupported checkpoint strategy")
        scope = (subscription.stream, subscription.group)
        transfer_marker: object | None = None
        current_lease: InMemoryPartitionLease | None = None
        wait_for_completion: asyncio.Event | None = None
        async with self._lock:
            self._require_open()
            state = self._stream(subscription.stream)
            self._partition(state, partition)
            self._validate_subscription(state.definition, subscription)
            if not self.start_mode_capabilities.supports(subscription.start):
                raise ValidationError("start position is not supported")
            self._reserve_strategy(scope, binding)
            key = CheckpointKey(subscription.stream, subscription.group, partition)
            current_lease = self._leases.get(key)
            if current_lease is not None:
                if not transfer:
                    self._release_strategy_reservation(scope, binding)
                    raise OwnershipError("partition is already owned")
                if key in self._transfers:
                    self._release_strategy_reservation(scope, binding)
                    raise OwnershipError("partition transfer is already in progress")
                transfer_marker = object()
                self._transfers[key] = transfer_marker
                current_lease._revocation_requested = True
                if current_lease._in_flight is not None:
                    wait_for_completion = current_lease._delivery_completed
            elif len(self._owners) >= self._max_active_leases:
                self._release_strategy_reservation(scope, binding)
                raise ResourceLimitError("active lease limit reached")
        try:
            if wait_for_completion is not None:
                await wait_for_completion.wait()
            async with self._lock:
                self._require_open()
                if transfer_marker is not None:
                    if self._transfers.get(key) is not transfer_marker:
                        raise OwnershipError("partition transfer was superseded")
                    if self._leases.get(key) is current_lease:
                        assert current_lease is not None
                        if current_lease._in_flight is not None:
                            raise OwnershipError("previous delivery is still in flight")
                        del self._leases[key]
                        del self._owners[key]
                    del self._transfers[key]
                elif key in self._leases:
                    raise OwnershipError("partition is already owned")
                generation = self._generations.get(key, 0) + 1
                token = OwnershipToken(subscription.owner_id, generation)
                lease = InMemoryPartitionLease(self, subscription, key, token, store)
                self._generations[key] = generation
                self._owners[key] = token
                self._leases[key] = lease
        except BaseException:
            await _finish_cleanup(
                self._cancel_acquire(
                    key,
                    scope,
                    binding,
                    current_lease,
                    transfer_marker,
                )
            )
            raise
        try:
            await self._initialize(lease)
        except BaseException:
            await _finish_cleanup(self._failed_initialization(lease, scope, binding))
            raise
        async with self._lock:
            self._group_strategies[scope] = binding
            self._release_strategy_reservation(scope, binding)
        return lease

    async def trim(self, stream: str, partition: int, before_offset: int) -> int:
        """Remove records below a cursor without changing offsets or producer state."""
        async with self._lock:
            self._require_open()
            state = self._stream(stream)
            part = self._partition(state, partition)
            self._validate_read(state.definition, before_offset, 1)
            boundary = min(before_offset, part.next_offset)
            removed = [record for record in part.records if record.offset < boundary]
            part.records = [
                record for record in part.records if record.offset >= boundary
            ]
            part.earliest_offset = max(part.earliest_offset, boundary)
            if removed:
                part.removed_through = removed[-1].appended_at
            return len(removed)

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            self._quiescing = True
            for lease in self._leases.values():
                lease._released = True
                lease._in_flight = None
                lease._delivery_completed.set()
            self._owners.clear()
            self._leases.clear()
            self._transfers.clear()

    async def _initialize(self, lease: InMemoryPartitionLease) -> None:
        if lease._store is not None:
            await validate_checkpoint_store_call(
                lease._store.fence(lease.key, lease.owner),
                cursor=None,
                returns="none",
            )
            existing = await validate_checkpoint_store_call(
                lease._store.load(lease.key),
                cursor=None,
                returns="optional_cursor",
            )
            if existing is None:
                cursor = await self._resolved_cursor(lease)
                await validate_checkpoint_store_call(
                    lease._store.compare_and_create(lease.key, cursor, lease.owner),
                    cursor=cursor,
                    returns="cursor",
                )
            await self._require_owner(lease.key, lease.owner)
            return
        async with self._lock:
            self._require_owner_locked(lease.key, lease.owner)
            if lease.key not in self._broker_cursors:
                state = self._stream(lease.key.stream)
                part = self._partition(state, lease.key.partition)
                offset = self._resolve_start_locked(
                    lease.subscription.start,
                    lease.key.stream,
                    lease.key.partition,
                    part,
                )
                self._broker_cursors[lease.key] = ResumeCursor.initialized(offset)

    async def _resolved_cursor(self, lease: InMemoryPartitionLease) -> ResumeCursor:
        async with self._lock:
            self._require_owner_locked(lease.key, lease.owner)
            state = self._stream(lease.key.stream)
            part = self._partition(state, lease.key.partition)
            offset = self._resolve_start_locked(
                lease.subscription.start,
                lease.key.stream,
                lease.key.partition,
                part,
            )
            return ResumeCursor.initialized(offset)

    async def _next(self, lease: InMemoryPartitionLease) -> StoredRecord | None:
        cursor = await self._load_cursor(lease)
        async with self._lock:
            self._require_owner_locked(lease.key, lease.owner)
            if lease._revocation_requested:
                raise OwnershipError("partition ownership is being revoked")
            if lease._in_flight is not None:
                raise LifecycleError("a delivery is already in flight")
            state = self._stream(lease.key.stream)
            part = self._partition(state, lease.key.partition)
            self._require_retained(
                lease.key.stream,
                lease.key.partition,
                cursor.offset,
                part,
                group=lease.key.group,
            )
            for record in part.records:
                if (
                    cursor.kind is CursorKind.INITIALIZED
                    and record.offset >= cursor.offset
                ):
                    lease._in_flight = record
                    lease._delivery_completed.clear()
                    return record
                if (
                    cursor.kind is CursorKind.LAST_SUCCESSFUL
                    and record.offset > cursor.offset
                ):
                    lease._in_flight = record
                    lease._delivery_completed.clear()
                    return record
            return None

    async def _checkpoint(
        self, lease: InMemoryPartitionLease, record: StoredRecord
    ) -> None:
        expected = await self._load_cursor(lease)
        cursor = ResumeCursor.last_successful(record.offset)
        if lease._store is not None:
            await self._require_owner(lease.key, lease.owner)
            try:
                await validate_checkpoint_store_call(
                    lease._store.save(lease.key, expected, cursor, lease.owner),
                    cursor=cursor,
                    returns="none",
                )
            except CheckpointPersistenceError:
                await self._stop(lease)
                raise
            async with self._lock:
                self._require_owner_locked(lease.key, lease.owner)
                self._complete_delivery_locked(lease)
            return
        async with self._lock:
            self._require_owner_locked(lease.key, lease.owner)
            current = self._broker_cursors.get(lease.key)
            if current != expected:
                raise CheckpointError("checkpoint changed concurrently")
            self._validate_advance(expected, cursor)
            self._broker_cursors[lease.key] = cursor
            self._complete_delivery_locked(lease)

    async def _load_cursor(self, lease: InMemoryPartitionLease) -> ResumeCursor:
        if lease._store is not None:
            try:
                cursor = await validate_checkpoint_store_call(
                    lease._store.load(lease.key),
                    cursor=None,
                    returns="optional_cursor",
                )
                if cursor is None:
                    error = AdapterContractError(
                        "checkpoint load returned None after initialization"
                    )
                    raise CheckpointPersistenceError(None, error) from error
            except CheckpointPersistenceError:
                await self._stop(lease)
                raise
            await self._require_owner(lease.key, lease.owner)
        else:
            async with self._lock:
                self._require_owner_locked(lease.key, lease.owner)
                cursor = self._broker_cursors.get(lease.key)
        if cursor is None:
            raise CheckpointError("checkpoint was not initialized")
        if not isinstance(cursor, ResumeCursor):
            raise CheckpointError("checkpoint was not initialized")
        return cursor

    async def _require_owner(self, key: CheckpointKey, owner: OwnershipToken) -> None:
        async with self._lock:
            self._require_owner_locked(key, owner)

    async def _stop(self, lease: InMemoryPartitionLease) -> None:
        async with self._lock:
            lease._stopped = True
            lease._in_flight = None
            lease._delivery_completed.set()

    async def _release(self, lease: InMemoryPartitionLease) -> None:
        async with self._lock:
            lease._released = True
            lease._in_flight = None
            lease._delivery_completed.set()
            if self._leases.get(lease.key) is lease:
                del self._leases[lease.key]
                del self._owners[lease.key]

    async def _cancel_acquire(
        self,
        key: CheckpointKey,
        scope: tuple[str, str],
        binding: _StrategyBinding,
        current_lease: InMemoryPartitionLease | None,
        transfer_marker: object | None,
    ) -> None:
        async with self._lock:
            if (
                transfer_marker is not None
                and self._transfers.get(key) is transfer_marker
            ):
                del self._transfers[key]
                if self._leases.get(key) is current_lease:
                    assert current_lease is not None
                    current_lease._revocation_requested = False
            self._release_strategy_reservation(scope, binding)

    async def _failed_initialization(
        self,
        lease: InMemoryPartitionLease,
        scope: tuple[str, str],
        binding: _StrategyBinding,
    ) -> None:
        await lease.release()
        async with self._lock:
            self._release_strategy_reservation(scope, binding)

    def _reserve_strategy(
        self, scope: tuple[str, str], binding: _StrategyBinding
    ) -> None:
        current = self._group_strategies.get(scope)
        if current is not None and current != binding:
            raise CheckpointStrategyError("consumer group checkpoint strategy is fixed")
        pending = self._pending_group_strategies.get(scope)
        if pending is not None and pending[0] != binding:
            raise CheckpointStrategyError(
                "consumer group checkpoint strategy initialization is in progress"
            )
        self._pending_group_strategies[scope] = (
            binding,
            1 if pending is None else pending[1] + 1,
        )

    def _release_strategy_reservation(
        self, scope: tuple[str, str], binding: _StrategyBinding
    ) -> None:
        pending = self._pending_group_strategies.get(scope)
        if pending is None or pending[0] != binding:
            return
        if pending[1] == 1:
            del self._pending_group_strategies[scope]
        else:
            self._pending_group_strategies[scope] = (binding, pending[1] - 1)

    @staticmethod
    def _complete_delivery_locked(lease: InMemoryPartitionLease) -> None:
        lease._in_flight = None
        lease._delivery_completed.set()

    def _resolve_start_locked(
        self,
        start: StartPosition,
        stream: str,
        partition: int,
        part: _PartitionState,
    ) -> int:
        if isinstance(start, Beginning):
            return part.earliest_offset
        if isinstance(start, End):
            return part.next_offset
        if isinstance(start, ExactOffset):
            self._require_retained(stream, partition, start.offset, part)
            return start.offset
        if isinstance(start, Timestamp):
            target = start.timestamp
        else:
            try:
                target = self._now() - start.age
            except OverflowError as error:
                raise ValidationError(
                    "relative time exceeds the clock range"
                ) from error
        if part.removed_through is not None and target <= part.removed_through:
            raise RetentionGapError(
                stream,
                partition,
                requested_timestamp=target,
                bounds=self._bounds(part),
            )
        for record in part.records:
            if record.appended_at >= target:
                return record.offset
        return part.next_offset

    def _validate_subscription(
        self, definition: StreamDefinition, subscription: Subscription
    ) -> None:
        limits = definition.limits
        if len(subscription.group) > limits.max_group_chars:
            raise ResourceLimitError("group name exceeds stream limit")
        if len(subscription.owner_id) > limits.max_owner_chars:
            raise ResourceLimitError("owner name exceeds stream limit")
        if isinstance(subscription.start, RelativeTime) and subscription.start.age > (
            timedelta(days=limits.max_relative_age_days)
        ):
            raise ResourceLimitError("relative time exceeds stream limit")

    @staticmethod
    def _validate_read(
        definition: StreamDefinition, from_offset: int, limit: int
    ) -> None:
        if (
            isinstance(from_offset, bool)
            or not isinstance(from_offset, int)
            or from_offset < 0
        ):
            raise ValidationError("from_offset must be a non-negative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValidationError("limit must be a positive integer")
        if limit > definition.limits.max_read_records:
            raise ResourceLimitError("read limit exceeds stream limit")

    @staticmethod
    def _validate_advance(expected: ResumeCursor, cursor: ResumeCursor) -> None:
        if (
            expected.kind is CursorKind.LAST_SUCCESSFUL
            and cursor.offset <= expected.offset
        ):
            raise CheckpointError("checkpoint must advance")
        if expected.kind is CursorKind.INITIALIZED and cursor.offset < expected.offset:
            raise CheckpointError("checkpoint precedes initialized start")

    @staticmethod
    def _bounds(part: _PartitionState) -> AvailableBounds:
        return AvailableBounds(part.earliest_offset, part.next_offset)

    @staticmethod
    def _require_retained(
        stream: str,
        partition: int,
        offset: int,
        part: _PartitionState,
        *,
        group: str | None = None,
    ) -> None:
        if offset < part.earliest_offset:
            raise RetentionGapError(
                stream,
                partition,
                requested_offset=offset,
                bounds=InMemoryPersistentLog._bounds(part),
                group=group,
            )

    def _stream(self, name: str) -> _StreamState:
        try:
            return self._streams[name]
        except KeyError as error:
            raise UnknownStreamError(name) from error

    @staticmethod
    def _partition(state: _StreamState, partition: int) -> _PartitionState:
        if isinstance(partition, bool) or not isinstance(partition, int):
            raise InvalidPartitionError("partition must be an integer")
        if partition < 0 or partition >= len(state.partitions):
            raise InvalidPartitionError("partition is out of range")
        return state.partitions[partition]

    def _now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValidationError("clock must return an aware datetime")
        return value

    def _require_open(self) -> None:
        if self._closed:
            raise LifecycleError("persistent log is closed")

    def _require_owner_locked(self, key: CheckpointKey, owner: OwnershipToken) -> None:
        self._require_open()
        if self._owners.get(key) != owner:
            raise OwnershipError("partition ownership has been lost")


class InMemoryPartitionLease:
    def __init__(
        self,
        log: InMemoryPersistentLog,
        subscription: Subscription,
        key: CheckpointKey,
        owner: OwnershipToken,
        store: CheckpointStore | None,
    ) -> None:
        self._log = log
        self.subscription = subscription
        self.key = key
        self.owner = owner
        self._store = store
        self._stopped = False
        self._released = False
        self._revocation_requested = False
        self._in_flight: StoredRecord | None = None
        self._delivery_completed = asyncio.Event()
        self._delivery_completed.set()

    @property
    def stopped(self) -> bool:
        return self._stopped

    async def next_record(self) -> StoredRecord | None:
        self._require_active()
        return await self._log._next(self)

    async def checkpoint(self, record: StoredRecord) -> None:
        self._require_active()
        await self._log._require_owner(self.key, self.owner)
        if record is not self._in_flight:
            raise CheckpointError("record is not the current in-flight delivery")
        await self._log._checkpoint(self, record)

    async def stop(self) -> None:
        await self._log._stop(self)

    async def release(self) -> None:
        if not self._released:
            await self._log._release(self)

    def _require_active(self) -> None:
        if self._released:
            raise LifecycleError("partition lease is released")
        if self._stopped:
            raise LifecycleError("partition lease is stopped")


async def _finish_cleanup(cleanup: Awaitable[None]) -> None:
    task = asyncio.ensure_future(cleanup)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
