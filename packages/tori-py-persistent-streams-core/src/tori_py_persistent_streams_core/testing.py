from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Protocol, runtime_checkable
from uuid import uuid4

from tori_py_persistent_streams_core.checkpoints import (
    CheckpointStrategy,
    ExternalCheckpointStrategy,
    InMemoryCheckpointStore,
)
from tori_py_persistent_streams_core.consumers import ConsumerRunner
from tori_py_persistent_streams_core.errors import (
    CheckpointPersistenceError,
    CheckpointStrategyError,
    IncompatibleStreamError,
    InvalidPartitionError,
    LifecycleError,
    OwnershipError,
    PoisonRecordError,
    PublishingConflictError,
    ResourceLimitError,
    RetentionGapError,
    StalePublishingIdError,
    ValidationError,
)
from tori_py_persistent_streams_core.models import (
    AppendRequest,
    Beginning,
    CheckpointKey,
    End,
    ExactOffset,
    PublishOutcome,
    RelativeTime,
    ResumeCursor,
    StreamDefinition,
    StreamLimits,
    Subscription,
    Timestamp,
)
from tori_py_persistent_streams_core.protocols import PersistentLog
from tori_py_persistent_streams_core.routing import DEFAULT_PARTITION_ROUTER

AdapterFactory = Callable[[], Awaitable[PersistentLog]]


@runtime_checkable
class TrimCapablePersistentLog(Protocol):
    async def trim(self, stream: str, partition: int, before_offset: int) -> int: ...


class _ConfigurableRouter:
    identity = "conformance-router-v1"

    def __init__(self, partition: int) -> None:
        self.partition = partition

    @property
    def compatibility_key(self) -> tuple[str, int]:
        return (self.identity, self.partition)

    def route(self, partition_key: bytes, partition_count: int) -> int:
        return self.partition % partition_count


async def conformance_declarations_and_sparse_order(factory: AdapterFactory) -> None:
    log = await factory()
    try:
        definition = StreamDefinition("conformance-order", 3)
        await log.declare_stream(definition)
        await log.declare_stream(definition)
        await _raises(
            IncompatibleStreamError,
            log.declare_stream(StreamDefinition(definition.name, 2)),
        )
        configured = StreamDefinition(
            "conformance-router", 2, router=_ConfigurableRouter(0)
        )
        await log.declare_stream(configured)
        await _raises(
            IncompatibleStreamError,
            log.declare_stream(
                StreamDefinition(configured.name, 2, router=_ConfigurableRouter(1))
            ),
        )
        keys = (b"alpha", b"beta", b"gamma", b"delta", b"epsilon")
        receipts = [
            await log.append(
                definition.name,
                AppendRequest(uuid4(), key, key, {"kind": b"conformance"}),
            )
            for key in keys
        ]
        for key, receipt in zip(keys, receipts, strict=True):
            expected = DEFAULT_PARTITION_ROUTER.route(key, definition.partition_count)
            _assert(
                receipt.partition == expected, "configured routing was not preserved"
            )
        for partition in range(definition.partition_count):
            page = await log.read(definition.name, partition, 0, len(keys))
            offsets = [record.offset for record in page.records]
            _assert(
                offsets == sorted(set(offsets)),
                "partition offsets were not strictly increasing",
            )
            _assert(
                all(record.partition == partition for record in page.records),
                "partition read crossed a partition",
            )
        concurrent = StreamDefinition("conformance-concurrent-appends", 1)
        await log.declare_stream(concurrent)
        await asyncio.gather(
            *(
                log.append(
                    concurrent.name,
                    AppendRequest(uuid4(), b"key", str(index).encode()),
                )
                for index in range(12)
            )
        )
        records = (await log.read(concurrent.name, 0, 0, 12)).records
        offsets = [record.offset for record in records]
        _assert(len(records) == 12, "concurrent append lost a record")
        _assert(
            offsets == sorted(set(offsets)),
            "concurrent append did not assign ordered unique offsets",
        )
    finally:
        await log.close()


async def conformance_start_modes_and_cursors(factory: AdapterFactory) -> None:
    log = await factory()
    try:
        stream = "conformance-starts"
        await log.declare_stream(StreamDefinition(stream, 1))
        await log.append(stream, AppendRequest(uuid4(), b"key", b"first"))
        await log.append(stream, AppendRequest(uuid4(), b"key", b"second"))
        records = (await log.read(stream, 0, 0, 10)).records
        capabilities = log.start_mode_capabilities
        starts = []
        if capabilities.beginning:
            starts.append(("beginning", Beginning(), records[0]))
        if capabilities.exact_offset:
            starts.append(("exact", ExactOffset(records[1].offset), records[1]))
        if capabilities.timestamp:
            starts.append(("timestamp", Timestamp(records[1].appended_at), records[1]))
        if capabilities.relative_time:
            starts.append(("relative", RelativeTime(timedelta(days=36500)), records[0]))
        for group, start, expected in starts:
            lease = await log.acquire(
                Subscription(stream, group, group, start),
                0,
                strategy=CheckpointStrategy.BROKER_MANAGED,
            )
            delivered = await lease.next_record()
            _assert(delivered == expected, f"{group} start resolved incorrectly")
            assert delivered is not None
            await lease.checkpoint(delivered)
            await lease.release()
            restarted = await log.acquire(
                Subscription(stream, group, f"{group}-restart", Beginning()),
                0,
                strategy=CheckpointStrategy.BROKER_MANAGED,
            )
            following = await restarted.next_record()
            if expected == records[0]:
                _assert(following == records[1], "checkpoint did not override start")
            else:
                _assert(following is None, "checkpoint restart repeated a record")
            await restarted.release()
        if capabilities.end:
            lease = await log.acquire(
                Subscription(stream, "end", "end", End()),
                0,
                strategy=CheckpointStrategy.BROKER_MANAGED,
            )
            _assert(await lease.next_record() is None, "end start included old records")
            await log.append(stream, AppendRequest(uuid4(), b"key", b"later"))
            later = await lease.next_record()
            _assert(
                later is not None and later.payload == b"later", "end was not stable"
            )
            await lease.release()
    finally:
        await log.close()


async def conformance_ownership_and_processing(factory: AdapterFactory) -> None:
    log = await factory()
    try:
        stream = "conformance-consumers"
        await log.declare_stream(StreamDefinition(stream, 1))
        await log.append(stream, AppendRequest(uuid4(), b"key", b"first"))
        first = await log.acquire(
            Subscription(stream, "group", "one", Beginning()),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )
        await _raises(
            OwnershipError,
            log.acquire(
                Subscription(stream, "group", "two", Beginning()),
                0,
                strategy=CheckpointStrategy.BROKER_MANAGED,
            ),
        )
        delivered = await first.next_record()
        assert delivered is not None
        transfer = asyncio.create_task(
            log.acquire(
                Subscription(stream, "group", "two", Beginning()),
                0,
                strategy=CheckpointStrategy.BROKER_MANAGED,
                transfer=True,
            )
        )
        await asyncio.sleep(0)
        _assert(not transfer.done(), "transfer overlapped an in-flight delivery")
        await first.checkpoint(delivered)
        second = await transfer
        await _raises(OwnershipError, first.next_record())
        await _raises(OwnershipError, first.checkpoint(delivered))
        await second.release()

        restored = await log.acquire(
            Subscription(stream, "cancelled-transfer", "one", Beginning()),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )
        pending = await restored.next_record()
        assert pending is not None
        cancelled_transfer = asyncio.create_task(
            log.acquire(
                Subscription(stream, "cancelled-transfer", "two", Beginning()),
                0,
                strategy=CheckpointStrategy.BROKER_MANAGED,
                transfer=True,
            )
        )
        await asyncio.sleep(0)
        cancelled_transfer.cancel()
        await _raises(asyncio.CancelledError, cancelled_transfer)
        await restored.checkpoint(pending)
        await restored.release()

        poison = await log.acquire(
            Subscription(stream, "poison", "one", Beginning()),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )

        async def fail(_record) -> None:
            raise RuntimeError("poison")

        await _raises(PoisonRecordError, ConsumerRunner().run_once(poison, fail))
        _assert(poison.stopped, "poison failure did not stop the lease")
        retry = await log.acquire(
            Subscription(stream, "poison", "two", Beginning()),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
            transfer=True,
        )
        redelivered = await retry.next_record()
        _assert(redelivered == delivered, "poison record was not redelivered")
        await retry.release()
    finally:
        await log.close()


async def conformance_external_checkpoints(factory: AdapterFactory) -> None:
    log = await factory()
    try:
        stream = "conformance-external"
        await log.declare_stream(StreamDefinition(stream, 1))
        await log.append(stream, AppendRequest(uuid4(), b"key", b"first"))
        await log.append(stream, AppendRequest(uuid4(), b"key", b"second"))
        strategy = ExternalCheckpointStrategy(
            "conformance-checkpoints", InMemoryCheckpointStore()
        )
        lease = await log.acquire(
            Subscription(stream, "group", "one", Beginning()),
            0,
            strategy=strategy,
        )
        seen = []

        async def handle(record) -> None:
            seen.append(record.payload)

        _assert(
            await ConsumerRunner().run_once(lease, handle, limit=1) == 1,
            "external checkpoint did not process a record",
        )
        await lease.release()
        restarted = await log.acquire(
            Subscription(stream, "group", "two", Beginning()),
            0,
            strategy=strategy,
        )
        await ConsumerRunner().run_once(restarted, handle, limit=1)
        _assert(seen == [b"first", b"second"], "external cursor did not resume")
        await restarted.release()
        await _raises(
            CheckpointStrategyError,
            log.acquire(
                Subscription(stream, "group", "three", Beginning()),
                0,
                strategy=ExternalCheckpointStrategy(
                    "other-checkpoints", strategy.store
                ),
            ),
        )
        await _raises(
            CheckpointStrategyError,
            log.acquire(
                Subscription(stream, "group", "four", Beginning()),
                0,
                strategy=ExternalCheckpointStrategy(
                    "conformance-checkpoints", InMemoryCheckpointStore()
                ),
            ),
        )
    finally:
        await log.close()


class _ConcurrentInitializationStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._cursors: dict[CheckpointKey, ResumeCursor] = {}
        self._arrivals = 0
        self._both_arrived = asyncio.Event()

    async def fence(self, key, owner) -> None:
        pass

    async def load(self, key):
        async with self._lock:
            return self._cursors.get(key)

    async def compare_and_create(self, key, cursor, owner):
        self._arrivals += 1
        if self._arrivals == 2:
            self._both_arrived.set()
        await self._both_arrived.wait()
        async with self._lock:
            return self._cursors.setdefault(key, cursor)

    async def save(self, key, expected, cursor, owner) -> None:
        async with self._lock:
            if self._cursors.get(key) != expected:
                raise RuntimeError("checkpoint changed concurrently")
            self._cursors[key] = cursor


async def conformance_concurrent_start_compare_create(factory: AdapterFactory) -> None:
    first_log, second_log = await asyncio.gather(factory(), factory())
    try:
        definition = StreamDefinition("conformance-concurrent-start", 1)
        await asyncio.gather(
            first_log.declare_stream(definition),
            second_log.declare_stream(definition),
        )
        request = AppendRequest(uuid4(), b"key", b"record")
        await asyncio.gather(
            first_log.append(definition.name, request),
            second_log.append(definition.name, request),
        )
        store = _ConcurrentInitializationStore()
        strategy = ExternalCheckpointStrategy("shared-conformance-store", store)
        first, second = await asyncio.gather(
            first_log.acquire(
                Subscription(definition.name, "group", "one", Beginning()),
                0,
                strategy=strategy,
            ),
            second_log.acquire(
                Subscription(definition.name, "group", "two", End()),
                0,
                strategy=strategy,
            ),
        )
        first_record, second_record = await asyncio.gather(
            first.next_record(), second.next_record()
        )
        _assert(
            (first_record is None) == (second_record is None)
            and (
                first_record is None
                or (
                    second_record is not None
                    and first_record.offset == second_record.offset
                    and first_record.payload == second_record.payload
                )
            ),
            "concurrent checkpoint initialization did not use one winning cursor",
        )
        await asyncio.gather(first.release(), second.release())
    finally:
        await asyncio.gather(first_log.close(), second_log.close())


class _FailBoundaryStore(InMemoryCheckpointStore):
    def __init__(self, boundary: str, *, runtime: bool = False) -> None:
        super().__init__()
        self.boundary = boundary
        self.runtime = runtime
        self.loads = 0

    async def fence(self, key, owner) -> None:
        if self.boundary == "fence":
            raise OSError("fence unavailable")
        await super().fence(key, owner)

    async def load(self, key):
        self.loads += 1
        if self.boundary == "load" and (not self.runtime or self.loads > 1):
            raise OSError("load unavailable")
        return await super().load(key)

    async def compare_and_create(self, key, cursor, owner):
        if self.boundary == "compare_and_create":
            raise OSError("compare-and-create unavailable")
        return await super().compare_and_create(key, cursor, owner)

    async def save(self, key, expected, cursor, owner) -> None:
        if self.boundary == "save":
            raise OSError("save unavailable")
        await super().save(key, expected, cursor, owner)


class _BlockingSaveStore(InMemoryCheckpointStore):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()

    async def save(self, key, expected, cursor, owner) -> None:
        self.entered.set()
        await asyncio.Event().wait()


async def conformance_checkpoint_failures_and_cancellation(
    factory: AdapterFactory,
) -> None:
    log = await factory()
    try:
        stream = "conformance-checkpoint-failures"
        await log.declare_stream(StreamDefinition(stream, 1))
        await log.append(stream, AppendRequest(uuid4(), b"key", b"record"))

        async def handle(_record) -> None:
            pass

        for boundary in ("fence", "load", "compare_and_create"):
            error = await _raises(
                CheckpointPersistenceError,
                log.acquire(
                    Subscription(stream, boundary, "one", Beginning()),
                    0,
                    strategy=ExternalCheckpointStrategy(
                        f"{boundary}-store", _FailBoundaryStore(boundary)
                    ),
                ),
            )
            assert isinstance(error, CheckpointPersistenceError)
            _assert(isinstance(error.cause, OSError), f"{boundary} cause was lost")
            if boundary == "compare_and_create":
                _assert(error.cursor is not None, "compare-create cursor was lost")
            else:
                _assert(error.cursor is None, f"{boundary} fabricated a cursor")

        for boundary in ("load", "save"):
            failing = await log.acquire(
                Subscription(stream, f"runtime-{boundary}", "one", Beginning()),
                0,
                strategy=ExternalCheckpointStrategy(
                    f"runtime-{boundary}-store",
                    _FailBoundaryStore(boundary, runtime=True),
                ),
            )
            error = await _raises(
                CheckpointPersistenceError,
                ConsumerRunner().run_once(failing, handle),
            )
            assert isinstance(error, CheckpointPersistenceError)
            _assert(isinstance(error.cause, OSError), f"{boundary} cause was lost")
            _assert(failing.stopped, f"{boundary} failure did not stop the partition")
            if boundary == "save":
                _assert(error.cursor is not None, "save failure omitted cursor")
            else:
                _assert(error.cursor is None, "load failure fabricated a cursor")

        blocking_store = _BlockingSaveStore()
        blocking_strategy = ExternalCheckpointStrategy("blocking-store", blocking_store)
        blocking = await log.acquire(
            Subscription(stream, "cancellation", "one", Beginning()),
            0,
            strategy=blocking_strategy,
        )
        task = asyncio.create_task(ConsumerRunner().run_once(blocking, handle))
        await blocking_store.entered.wait()
        task.cancel()
        await _raises(asyncio.CancelledError, task)
        replacement = await log.acquire(
            Subscription(stream, "cancellation", "two", Beginning()),
            0,
            strategy=blocking_strategy,
        )
        _assert(
            await replacement.next_record() is not None,
            "checkpoint cancellation advanced progress",
        )
        await replacement.release()
    finally:
        await log.close()


async def conformance_producers_retention_and_limits(factory: AdapterFactory) -> None:
    log = await factory()
    try:
        stream = "conformance-producers"
        limits = StreamLimits(max_payload_bytes=4, max_read_records=2)
        await log.declare_stream(StreamDefinition(stream, 1, limits))
        unnamed = AppendRequest(uuid4(), b"key", b"one")
        await log.append(stream, unnamed)
        await log.append(stream, unnamed)
        named = AppendRequest(
            uuid4(), b"key", b"two", producer_name="producer", publishing_id=5
        )
        confirmed = await log.append(stream, named)
        duplicate = await log.append(stream, named)
        _assert(confirmed.outcome is PublishOutcome.CONFIRMED, "append not confirmed")
        _assert(
            duplicate.outcome is PublishOutcome.DEDUPLICATED,
            "named retry was not deduplicated",
        )
        await _raises(
            PublishingConflictError,
            log.append(
                stream,
                AppendRequest(
                    uuid4(),
                    b"key",
                    b"bad",
                    producer_name="producer",
                    publishing_id=5,
                ),
            ),
        )
        newer = AppendRequest(
            uuid4(), b"key", b"new", producer_name="producer", publishing_id=7
        )
        await log.append(stream, newer)
        await _raises(StalePublishingIdError, log.append(stream, named))
        await _raises(
            ResourceLimitError,
            log.append(stream, AppendRequest(uuid4(), b"key", b"large")),
        )
        await _raises(ResourceLimitError, log.read(stream, 0, 0, 3))
        if isinstance(log, TrimCapablePersistentLog):
            records = (await log.read(stream, 0, 0, 2)).records
            stale = await log.acquire(
                Subscription(stream, "stale", "one", Beginning()),
                0,
                strategy=CheckpointStrategy.BROKER_MANAGED,
            )
            stale_record = await stale.next_record()
            assert stale_record is not None
            await stale.checkpoint(stale_record)
            await stale.release()
            await log.trim(stream, 0, records[-1].offset + 1)
            await _raises(RetentionGapError, log.read(stream, 0, 0, 1))
            stale_restart = await log.acquire(
                Subscription(stream, "stale", "two", Beginning()),
                0,
                strategy=CheckpointStrategy.BROKER_MANAGED,
            )
            await _raises(RetentionGapError, stale_restart.next_record())
            await stale_restart.release()
            _assert(
                (await log.append(stream, newer)).outcome
                is PublishOutcome.DEDUPLICATED,
                "retention removed producer state",
            )
    finally:
        await log.close()
    await _raises(LifecycleError, log.declare_stream(StreamDefinition("closed", 1)))


async def conformance_validation_and_closed_lifecycle(factory: AdapterFactory) -> None:
    log = await factory()
    stream = "conformance-validation"
    definition = StreamDefinition(stream, 1)
    await log.declare_stream(definition)
    await _raises(InvalidPartitionError, log.bounds(stream, 1))
    await _raises(ValidationError, log.read(stream, 0, -1, 1))
    await _raises(ValidationError, log.read(stream, 0, 0, 0))
    await log.close()
    await _raises(LifecycleError, log.declare_stream(StreamDefinition("closed", 1)))
    await _raises(
        LifecycleError,
        log.append(stream, AppendRequest(uuid4(), b"key", b"record")),
    )
    await _raises(LifecycleError, log.bounds(stream, 0))
    await _raises(LifecycleError, log.read(stream, 0, 0, 1))
    await _raises(
        LifecycleError,
        log.acquire(
            Subscription(stream, "group", "owner", Beginning()),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        ),
    )


async def conformance_cancellation(factory: AdapterFactory) -> None:
    log = await factory()
    try:
        stream = "conformance-cancellation"
        await log.declare_stream(StreamDefinition(stream, 1))
        await log.append(stream, AppendRequest(uuid4(), b"key", b"record"))
        lease = await log.acquire(
            Subscription(stream, "group", "one", Beginning()),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )
        entered = asyncio.Event()

        async def block(_record) -> None:
            entered.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(ConsumerRunner().run_once(lease, block))
        await entered.wait()
        task.cancel()
        await _raises(asyncio.CancelledError, task)
        replacement = await log.acquire(
            Subscription(stream, "group", "two", Beginning()),
            0,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )
        redelivered = await replacement.next_record()
        _assert(redelivered is not None, "cancellation advanced the checkpoint")
        await replacement.release()
    finally:
        await log.close()


async def run_conformance_suite(factory: AdapterFactory) -> None:
    """Run framework-independent public contract cases against isolated logs."""
    for case in (
        conformance_declarations_and_sparse_order,
        conformance_start_modes_and_cursors,
        conformance_ownership_and_processing,
        conformance_external_checkpoints,
        conformance_concurrent_start_compare_create,
        conformance_checkpoint_failures_and_cancellation,
        conformance_producers_retention_and_limits,
        conformance_cancellation,
        conformance_validation_and_closed_lifecycle,
    ):
        await case(factory)


async def _raises(
    expected: type[BaseException], awaitable: Awaitable[object]
) -> BaseException:
    try:
        await awaitable
    except expected as error:
        return error
    except BaseException as error:
        raise AssertionError(
            f"expected {expected.__name__}, got {type(error).__name__}"
        ) from error
    raise AssertionError(f"expected {expected.__name__}")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


__all__ = [
    "AdapterFactory",
    "TrimCapablePersistentLog",
    "conformance_cancellation",
    "conformance_checkpoint_failures_and_cancellation",
    "conformance_concurrent_start_compare_create",
    "conformance_declarations_and_sparse_order",
    "conformance_external_checkpoints",
    "conformance_ownership_and_processing",
    "conformance_producers_retention_and_limits",
    "conformance_start_modes_and_cursors",
    "conformance_validation_and_closed_lifecycle",
    "run_conformance_suite",
]
