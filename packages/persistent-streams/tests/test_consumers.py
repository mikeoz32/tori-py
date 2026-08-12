from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from persistent_streams import (
    AdapterContractError,
    AppendRequest,
    Beginning,
    CheckpointError,
    CheckpointPersistenceError,
    CheckpointStrategy,
    CheckpointStrategyError,
    ConsumerRunner,
    End,
    ExactOffset,
    ExternalCheckpointStrategy,
    InMemoryCheckpointStore,
    InMemoryPersistentLog,
    LifecycleError,
    OwnershipError,
    PoisonRecordError,
    RelativeTime,
    ResourceLimitError,
    ResumeCursor,
    RetentionGapError,
    StartModeCapabilities,
    StoredRecord,
    StreamDefinition,
    StreamLimits,
    Subscription,
    Timestamp,
    ValidationError,
)


async def _append(log: InMemoryPersistentLog, payload: bytes) -> None:
    await log.append("events", AppendRequest(uuid4(), b"one", payload))


@pytest.mark.asyncio
@pytest.mark.parametrize("external", [False, True])
async def test_checkpoint_after_success_and_restart(external: bool) -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))
    await _append(log, b"first")
    await _append(log, b"second")
    strategy = (
        ExternalCheckpointStrategy("test-checkpoints", InMemoryCheckpointStore())
        if external
        else CheckpointStrategy.BROKER_MANAGED
    )
    lease = await log.acquire(
        Subscription("events", "group", "one", Beginning()), 0, strategy=strategy
    )
    seen: list[bytes] = []

    async def handle(record) -> None:
        seen.append(record.payload)

    assert await ConsumerRunner().run_once(lease, handle, limit=1) == 1
    await lease.release()
    restarted = await log.acquire(
        Subscription("events", "group", "two", End()), 0, strategy=strategy
    )
    assert await ConsumerRunner().run_once(restarted, handle, limit=2) == 1
    assert seen == [b"first", b"second"]


@pytest.mark.asyncio
async def test_poison_stops_partition_and_reacquisition_redelivers() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))
    await _append(log, b"poison")
    lease = await log.acquire(
        Subscription("events", "group", "one", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )

    async def fail(_record) -> None:
        raise RuntimeError("failed")

    with pytest.raises(PoisonRecordError) as caught:
        await ConsumerRunner().run_once(lease, fail)
    assert caught.value.offset == 0
    assert lease.stopped

    replacement = await log.acquire(
        Subscription("events", "group", "two", End()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
        transfer=True,
    )
    redelivered = await replacement.next_record()
    assert redelivered is not None
    assert redelivered.payload == b"poison"


@pytest.mark.asyncio
async def test_transfer_fences_old_owner_and_cancellation_releases() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))
    await _append(log, b"record")
    first = await log.acquire(
        Subscription("events", "group", "one", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )
    second = await log.acquire(
        Subscription("events", "group", "two", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
        transfer=True,
    )
    with pytest.raises(OwnershipError):
        await first.next_record()
    await second.release()

    cancellable = await log.acquire(
        Subscription("events", "cancel", "one", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )
    entered = asyncio.Event()

    async def wait(_record) -> None:
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(ConsumerRunner().run_once(cancellable, wait))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await log.acquire(
        Subscription("events", "cancel", "two", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )


@pytest.mark.asyncio
async def test_all_start_modes_and_retention_gaps() -> None:
    times = iter(
        [
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            datetime(2026, 1, 1, 12, 30, tzinfo=UTC),
        ]
    )
    log = InMemoryPersistentLog(clock=lambda: next(times))
    await log.declare_stream(StreamDefinition("events", 1))
    await _append(log, b"ten")
    await _append(log, b"eleven")

    starts = {
        "beginning": (Beginning(), b"ten"),
        "exact": (ExactOffset(2), b"eleven"),
        "timestamp": (Timestamp(datetime(2026, 1, 1, 10, 30, tzinfo=UTC)), b"eleven"),
        "relative": (RelativeTime(timedelta(minutes=90)), b"eleven"),
    }
    for group, (start, expected) in starts.items():
        lease = await log.acquire(
            Subscription("events", group, group, start),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )
        record = await lease.next_record()
        assert record is not None
        assert record.payload == expected
        await lease.release()
    end = await log.acquire(
        Subscription("events", "end", "end", End()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )
    assert await end.next_record() is None
    await _append(log, b"later")
    later = await end.next_record()
    assert later is not None
    assert later.payload == b"later"

    await log.trim("events", 0, 2)
    with pytest.raises(RetentionGapError):
        await log.acquire(
            Subscription("events", "gap", "gap", ExactOffset(0)),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )


@pytest.mark.asyncio
async def test_lease_checkpoints_only_its_exact_in_flight_record() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))
    await _append(log, b"first")
    await _append(log, b"second")
    lease = await log.acquire(
        Subscription("events", "group", "one", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )
    delivered = await lease.next_record()
    assert delivered is not None

    with pytest.raises(LifecycleError, match="delivery is already in flight"):
        await lease.next_record()
    later = (await log.read("events", 0, 2, 1)).records[0]
    with pytest.raises(CheckpointError):
        await lease.checkpoint(later)
    fabricated = StoredRecord(
        delivered.record_id,
        delivered.stream,
        delivered.partition_key,
        delivered.payload,
        delivered.headers,
        delivered.partition,
        delivered.offset,
        delivered.appended_at,
    )
    with pytest.raises(CheckpointError):
        await lease.checkpoint(fabricated)

    await lease.checkpoint(delivered)
    assert (await lease.next_record()) is later
    await lease.stop()
    replacement = await log.acquire(
        Subscription("events", "group", "two", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
        transfer=True,
    )
    assert (await replacement.next_record()) is later


@pytest.mark.asyncio
async def test_transfer_waits_for_blocked_handler_without_overlap() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))
    await _append(log, b"first")
    await _append(log, b"second")
    first = await log.acquire(
        Subscription("events", "group", "one", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )
    entered = asyncio.Event()
    finish = asyncio.Event()
    active_handlers = 0
    maximum_handlers = 0

    async def blocked(_record) -> None:
        nonlocal active_handlers, maximum_handlers
        active_handlers += 1
        maximum_handlers = max(maximum_handlers, active_handlers)
        entered.set()
        await finish.wait()
        active_handlers -= 1

    old_run = asyncio.create_task(ConsumerRunner().run_once(first, blocked))
    await entered.wait()
    transfer = asyncio.create_task(
        log.acquire(
            Subscription("events", "group", "two", Beginning()),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
            transfer=True,
        )
    )
    await asyncio.sleep(0)
    assert not transfer.done()
    assert active_handlers == 1

    finish.set()
    assert await old_run == 1
    second = await transfer
    assert active_handlers == 0
    assert await ConsumerRunner().run_once(second, blocked) == 1
    assert maximum_handlers == 1


@pytest.mark.asyncio
async def test_cancelled_blocked_transfer_restores_old_lease() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))
    await _append(log, b"record")
    lease = await log.acquire(
        Subscription("events", "group", "one", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )
    record = await lease.next_record()
    assert record is not None
    transfer = asyncio.create_task(
        log.acquire(
            Subscription("events", "group", "two", Beginning()),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
            transfer=True,
        )
    )
    await asyncio.sleep(0)
    transfer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await transfer

    await lease.checkpoint(record)
    assert await lease.next_record() is None


class _FailInitializationStore(InMemoryCheckpointStore):
    async def fence(self, key, owner) -> None:
        raise OSError("unavailable")


class _FailCompareCreateStore(InMemoryCheckpointStore):
    async def compare_and_create(self, key, cursor, owner):
        raise OSError("compare-create unavailable")


class _BlockingFenceStore(InMemoryCheckpointStore):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()

    async def fence(self, key, owner) -> None:
        self.entered.set()
        await asyncio.Event().wait()


class _BeginningOnlyLog(InMemoryPersistentLog):
    start_mode_capabilities = StartModeCapabilities(beginning=True)


class _BlockingInitializationStore(InMemoryCheckpointStore):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.proceed = asyncio.Event()

    async def fence(self, key, owner) -> None:
        if key.partition == 0:
            self.entered.set()
            await self.proceed.wait()
        await super().fence(key, owner)


@pytest.mark.asyncio
async def test_concurrent_partitions_reserve_the_same_pending_strategy() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 2))
    store = _BlockingInitializationStore()
    strategy = ExternalCheckpointStrategy("test-checkpoints", store)
    first_task = asyncio.create_task(
        log.acquire(
            Subscription("events", "group", "one", Beginning()),
            0,
            strategy=strategy,
        )
    )
    await store.entered.wait()
    second = await log.acquire(
        Subscription("events", "group", "two", Beginning()),
        1,
        strategy=strategy,
    )
    store.proceed.set()
    first = await first_task

    await first.release()
    await second.release()


@pytest.mark.asyncio
async def test_failed_initialization_does_not_fix_group_strategy() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))

    with pytest.raises(CheckpointPersistenceError) as caught:
        await log.acquire(
            Subscription("events", "group", "one", Beginning()),
            0,
            strategy=ExternalCheckpointStrategy(
                "failed-checkpoints", _FailInitializationStore()
            ),
        )
    assert caught.value.cursor is None
    assert isinstance(caught.value.cause, OSError)

    lease = await log.acquire(
        Subscription("events", "group", "two", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )
    await lease.release()
    with pytest.raises(CheckpointStrategyError):
        await log.acquire(
            Subscription("events", "group", "three", Beginning()),
            0,
            strategy=ExternalCheckpointStrategy(
                "other-checkpoints", InMemoryCheckpointStore()
            ),
        )


@pytest.mark.asyncio
async def test_compare_create_failure_has_cursor_and_releases_reservation() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))
    with pytest.raises(CheckpointPersistenceError) as caught:
        await log.acquire(
            Subscription("events", "group", "one", Beginning()),
            0,
            strategy=ExternalCheckpointStrategy(
                "failed-checkpoints", _FailCompareCreateStore()
            ),
        )

    assert caught.value.cursor == ResumeCursor.initialized(0)
    assert isinstance(caught.value.cause, OSError)
    replacement = await log.acquire(
        Subscription("events", "group", "two", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )
    await replacement.release()


@pytest.mark.asyncio
async def test_cancelled_initialization_releases_owner_and_reservation() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))
    store = _BlockingFenceStore()
    acquisition = asyncio.create_task(
        log.acquire(
            Subscription("events", "group", "one", Beginning()),
            0,
            strategy=ExternalCheckpointStrategy("blocked-checkpoints", store),
        )
    )
    await store.entered.wait()
    acquisition.cancel()
    with pytest.raises(asyncio.CancelledError):
        await acquisition

    replacement = await log.acquire(
        Subscription("events", "group", "two", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )
    await replacement.release()


@pytest.mark.asyncio
async def test_external_group_binds_identity_and_exact_store_object() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))
    store = InMemoryCheckpointStore()
    lease = await log.acquire(
        Subscription("events", "group", "one", Beginning()),
        0,
        strategy=ExternalCheckpointStrategy("primary", store),
    )
    await lease.release()

    same = await log.acquire(
        Subscription("events", "group", "two", Beginning()),
        0,
        strategy=ExternalCheckpointStrategy("primary", store),
    )
    await same.release()
    with pytest.raises(CheckpointStrategyError):
        await log.acquire(
            Subscription("events", "group", "three", Beginning()),
            0,
            strategy=ExternalCheckpointStrategy("primary", InMemoryCheckpointStore()),
        )
    with pytest.raises(CheckpointStrategyError):
        await log.acquire(
            Subscription("events", "group", "four", Beginning()),
            0,
            strategy=ExternalCheckpointStrategy("secondary", store),
        )


class _FailRuntimeLoadStore(InMemoryCheckpointStore):
    def __init__(self) -> None:
        super().__init__()
        self.loads = 0

    async def load(self, key):
        self.loads += 1
        if self.loads > 1:
            raise OSError("load unavailable")
        return await super().load(key)


class _MalformedLoadStore(InMemoryCheckpointStore):
    async def load(self, key):
        return "invalid"


class _MalformedFenceStore(InMemoryCheckpointStore):
    async def fence(self, key, owner):
        await super().fence(key, owner)
        return "invalid"


class _MalformedCompareCreateStore(InMemoryCheckpointStore):
    async def compare_and_create(self, key, cursor, owner):
        return "invalid"


class _MalformedSaveStore(InMemoryCheckpointStore):
    async def save(self, key, expected, cursor, owner):
        await super().save(key, expected, cursor, owner)
        return "invalid"


class _MalformedRuntimeLoadStore(InMemoryCheckpointStore):
    def __init__(self, result: object) -> None:
        super().__init__()
        self.loads = 0
        self.result = result

    async def load(self, key):
        self.loads += 1
        if self.loads > 1:
            return self.result
        return await super().load(key)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("store", "cursor"),
    [
        (_MalformedFenceStore(), None),
        (_MalformedLoadStore(), None),
        (_MalformedCompareCreateStore(), ResumeCursor.initialized(0)),
    ],
)
async def test_malformed_checkpoint_initialization_result_is_typed(
    store: InMemoryCheckpointStore, cursor: ResumeCursor | None
) -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))

    with pytest.raises(CheckpointPersistenceError) as caught:
        await log.acquire(
            Subscription("events", "group", "one", Beginning()),
            0,
            strategy=ExternalCheckpointStrategy("malformed", store),
        )

    assert caught.value.cursor == cursor
    assert isinstance(caught.value.cause, AdapterContractError)


@pytest.mark.asyncio
async def test_malformed_checkpoint_save_result_is_typed_and_stops_lease() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))
    await log.append("events", AppendRequest(uuid4(), b"key"))
    lease = await log.acquire(
        Subscription("events", "group", "one", Beginning()),
        0,
        strategy=ExternalCheckpointStrategy("malformed-save", _MalformedSaveStore()),
    )
    record = await lease.next_record()
    assert record is not None

    with pytest.raises(CheckpointPersistenceError) as caught:
        await lease.checkpoint(record)

    assert isinstance(caught.value.cause, AdapterContractError)
    assert caught.value.__cause__ is caught.value.cause
    assert lease.stopped


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [None, "invalid"])
async def test_malformed_runtime_load_result_is_typed_and_stops_lease(
    result: object,
) -> None:
    store = _MalformedRuntimeLoadStore(result)
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))
    lease = await log.acquire(
        Subscription("events", "group", "one", Beginning()),
        0,
        strategy=ExternalCheckpointStrategy("malformed-runtime", store),
    )

    with pytest.raises(CheckpointPersistenceError) as caught:
        await lease.next_record()

    assert caught.value.cursor is None
    assert isinstance(caught.value.cause, AdapterContractError)
    assert lease.stopped


@pytest.mark.asyncio
async def test_runtime_external_load_failure_is_typed_and_stops_lease() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))
    lease = await log.acquire(
        Subscription("events", "group", "one", Beginning()),
        0,
        strategy=ExternalCheckpointStrategy("primary", _FailRuntimeLoadStore()),
    )

    with pytest.raises(CheckpointPersistenceError) as caught:
        await lease.next_record()

    assert caught.value.cursor is None
    assert isinstance(caught.value.cause, OSError)
    assert lease.stopped


@pytest.mark.asyncio
async def test_relative_time_limit_and_clock_overflow_are_typed() -> None:
    limited = InMemoryPersistentLog()
    await limited.declare_stream(
        StreamDefinition("limited", 1, StreamLimits(max_relative_age_days=1))
    )
    with pytest.raises(ResourceLimitError, match="relative time"):
        await limited.acquire(
            Subscription("limited", "group", "one", RelativeTime(timedelta(days=2))),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )

    boundary = InMemoryPersistentLog(clock=lambda: datetime.min.replace(tzinfo=UTC))
    await boundary.declare_stream(StreamDefinition("boundary", 1))
    with pytest.raises(ValidationError, match="clock range"):
        await boundary.acquire(
            Subscription("boundary", "group", "one", RelativeTime(timedelta(days=1))),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )
    replacement = await boundary.acquire(
        Subscription("boundary", "group", "two", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )
    await replacement.release()


@pytest.mark.asyncio
async def test_unsupported_start_is_rejected_before_ownership() -> None:
    log = _BeginningOnlyLog()
    await log.declare_stream(StreamDefinition("events", 1))
    with pytest.raises(ValidationError, match="not supported"):
        await log.acquire(
            Subscription("events", "group", "one", End()),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )
    lease = await log.acquire(
        Subscription("events", "group", "two", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )
    await lease.release()
