from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from rstream import (
    Consumer,
    ConsumerOffsetSpecification,
    OffsetSpecification,
    OffsetType,
)
from rstream.consumer import EventContext, MessageContext
from rstream.exceptions import OffsetNotFound
from rstream.recovery import BackOffRecoveryStrategy
from tori_py_persistent_streams_core import (
    AvailableBounds,
    Beginning,
    CheckpointKey,
    CheckpointPersistenceError,
    CheckpointStrategy,
    CursorKind,
    End,
    ExactOffset,
    ExternalCheckpointStrategy,
    LifecycleError,
    OwnershipError,
    OwnershipToken,
    ResumeCursor,
    RetentionGapError,
    StoredRecord,
    Subscription,
    ValidationError,
)
from tori_py_persistent_streams_core.checkpoints import validate_checkpoint_store_call

from tori_py_persistent_streams_rabbitmq._cursor_codec import (
    decode_cursor,
    encode_cursor,
)
from tori_py_persistent_streams_rabbitmq._envelope import EnvelopeKind
from tori_py_persistent_streams_rabbitmq._shared import (
    best_effort,
    best_effort_close,
    decode_message,
    envelope_limits,
    safe_amqp_decoder,
    stored_record,
)

if TYPE_CHECKING:
    from tori_py_persistent_streams_rabbitmq.log import RabbitMqPersistentLog


class RabbitMqPartitionLease:
    def __init__(
        self,
        log: RabbitMqPersistentLog,
        subscription: Subscription,
        key: CheckpointKey,
        owner: OwnershipToken,
        strategy: CheckpointStrategy | ExternalCheckpointStrategy,
    ) -> None:
        self._log = log
        self._subscription = subscription
        self._key = key
        self._owner = owner
        self._strategy = strategy
        self._cursor: ResumeCursor | None = None
        self._consumer: Consumer | None = None
        self._subscriber_id: int | None = None
        self._queue: asyncio.Queue[tuple[int, StoredRecord]] = asyncio.Queue(
            maxsize=log.options.callback_queue_capacity
        )
        self._in_flight: StoredRecord | None = None
        self._stopped = False
        self._released = False
        self._last_delivered = -1
        self._revocation_requested = False
        self._delivery_completed = asyncio.Event()
        self._delivery_completed.set()
        self._delivery_ready = asyncio.Event()
        self._callback_error: BaseException | None = None
        self._state_lock = asyncio.Lock()
        self._active_generation = 0
        self._active = False
        self._intake_open = False
        self._activation_ready = asyncio.Event()
        self._pending_barrier: UUID | None = None
        self._resource_generation = 0
        self._checkpoint_lock = asyncio.Lock()
        self._checkpoint_task: asyncio.Task[object] | None = None
        self._fail_closed_task: asyncio.Task[None] | None = None
        self._retention_checked_generation = 0
        self._strategy_initialized = False

    @property
    def key(self) -> CheckpointKey:
        return self._key

    @property
    def owner(self) -> OwnershipToken:
        return self._owner

    @property
    def stopped(self) -> bool:
        return self._stopped

    async def initialize(self) -> None:
        if self._consumer is not None:
            return
        self._resource_generation = self._log._resource_generation
        consumer = Consumer(
            **self._log.options.connection.driver_kwargs(),
            on_close_handler=self._log._close_callback(self._resource_generation),
            recovery_strategy=BackOffRecoveryStrategy(False),
        )
        await self._log._within(consumer.start())
        resource_generation = self._resource_generation

        async def callback(message: object, context: MessageContext) -> None:
            async with self._state_lock:
                if (
                    self._released
                    or self._stopped
                    or not self._active
                    or resource_generation != self._log._resource_generation
                ):
                    return
                generation = self._active_generation
                pending_barrier = self._pending_barrier
                wait_for_in_flight = (
                    not self._intake_open
                    and pending_barrier is None
                    and not self._delivery_completed.is_set()
                )
            if wait_for_in_flight:
                await self._delivery_completed.wait()
                return
            if generation != self._retention_checked_generation:
                cursor = self._cursor
                if cursor is not None:
                    try:
                        await self._require_retained(cursor.offset)
                    except BaseException as error:
                        self._callback_error = error
                        self._stopped = True
                        self._delivery_ready.set()
                        self._activation_ready.set()
                        return
                self._retention_checked_generation = generation
            try:
                envelope = decode_message(
                    message,
                    envelope_limits(self._log._definition(self._key.stream)),
                )
            except BaseException as error:
                self._callback_error = error
                self._stopped = True
                self._delivery_ready.set()
                self._activation_ready.set()
                return
            if envelope.kind is EnvelopeKind.BARRIER:
                if envelope.record_id == pending_barrier:
                    try:
                        cursor = await self._create_cursor(
                            ResumeCursor.initialized(context.offset), generation
                        )
                    except BaseException as error:
                        self._callback_error = error
                        self._stopped = True
                    else:
                        async with self._state_lock:
                            if generation == self._active_generation and self._active:
                                self._cursor = cursor
                                self._pending_barrier = None
                                self._intake_open = True
                                self._activation_ready.set()
                    self._delivery_ready.set()
                return
            record = stored_record(
                envelope, context, self._key.stream, self._key.partition
            )
            async with self._state_lock:
                if (
                    generation != self._active_generation
                    or not self._intake_open
                    or not self._active
                ):
                    return
                cursor = self._cursor
            if record.offset <= self._last_delivered:
                self._stopped = True
                return
            if (
                cursor is not None
                and cursor.kind is CursorKind.LAST_SUCCESSFUL
                and record.offset <= cursor.offset
            ):
                return
            self._last_delivered = record.offset
            await self._queue.put((generation, record))
            self._delivery_ready.set()

        async def consumer_update(
            active: bool, context: EventContext
        ) -> OffsetSpecification:
            del context
            if not active:
                async with self._state_lock:
                    self._intake_open = False
                    demoted_generation = self._active_generation
                await self._delivery_completed.wait()
                async with self._state_lock:
                    if demoted_generation == self._active_generation:
                        self._active = False
                        self._active_generation += 1
                        self._retention_checked_generation = 0
                        self._clear_queue()
                return OffsetSpecification(OffsetType.NEXT, 0)
            async with self._state_lock:
                self._active_generation += 1
                generation = self._active_generation
                self._active = True
                self._intake_open = False
                self._retention_checked_generation = 0
                self._clear_queue()
            try:
                current = await self._load_cursor()
                if current is None:
                    start = self._subscription.start
                    if isinstance(start, End):
                        self._pending_barrier = await self._log._write_barrier(
                            self._log._physical(self._key.stream, self._key.partition)
                        )
                        return OffsetSpecification(OffsetType.FIRST, 0)
                    offset = await self._resolve_start()
                    current = await self._create_cursor(
                        ResumeCursor.initialized(offset), generation
                    )
                await self._require_retained(current.offset)
            except BaseException as error:
                self._callback_error = error
                self._stopped = True
                self._delivery_ready.set()
                self._activation_ready.set()
                return OffsetSpecification(OffsetType.NEXT, 0)
            async with self._state_lock:
                if generation == self._active_generation and self._active:
                    self._cursor = current
                    self._intake_open = True
                    self._activation_ready.set()
            offset = current.offset
            return OffsetSpecification(OffsetType.OFFSET, offset)

        try:
            self._subscriber_id = await self._log._within(
                consumer.subscribe(
                    self._log._physical(self._key.stream, self._key.partition),
                    cast(Any, callback),
                    decoder=safe_amqp_decoder,
                    offset_specification=ConsumerOffsetSpecification(OffsetType.FIRST),
                    initial_credit=self._log.options.initial_credit,
                    properties={
                        "single-active-consumer": "true",
                        "name": self._sac_name,
                    },
                    subscriber_name=self._sac_name,
                    consumer_update_listener=consumer_update,
                )
            )
        except BaseException:
            await best_effort_close(consumer)
            raise
        self._consumer = consumer
        try:
            await self._require_retained_after_subscription()
        except BaseException:
            await self._unsubscribe()
            self._log._leases.pop(self._key, None)
            self._log._discard_strategy_reservation(self._key)
            raise
        self._strategy_initialized = True
        self._log._commit_strategy(self._key)

    def _clear_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return

    def fail_closed(self, generation: int) -> None:
        if generation != self._resource_generation:
            return
        self._intake_open = False
        self._active = False
        self._active_generation += 1
        self._stopped = True
        self._clear_queue()
        self._delivery_ready.set()
        self._activation_ready.set()
        checkpoint = self._checkpoint_task
        if checkpoint is not None and not checkpoint.done():
            checkpoint.cancel()
        self._fail_closed_task = asyncio.create_task(
            self._finish_fail_closed(checkpoint)
        )

    async def _finish_fail_closed(
        self, checkpoint: asyncio.Task[object] | None
    ) -> None:
        if checkpoint is not None:
            await asyncio.gather(checkpoint, return_exceptions=True)
        async with self._checkpoint_lock:
            self._delivery_completed.set()

    @property
    def _sac_name(self) -> str:
        identity = (
            f"{self._key.stream}\0{self._key.group}\0{self._key.partition}"
        ).encode()
        return f"ps-{hashlib.sha256(identity).hexdigest()}"

    async def next_record(self) -> StoredRecord | None:
        while True:
            async with self._state_lock:
                if self._active or self._stopped:
                    break
                self._activation_ready.clear()
            await self._activation_ready.wait()
            self._raise_callback_error()
        self._raise_callback_error()
        self._require_owner()
        if self._revocation_requested:
            raise OwnershipError("partition lease transfer is pending")
        if self._in_flight is not None:
            raise OwnershipError("previous delivery has not been checkpointed")
        try:
            generation, record = self._queue.get_nowait()
        except asyncio.QueueEmpty:
            try:
                generation, record = await asyncio.wait_for(self._queue.get(), 0.25)
            except TimeoutError:
                self._raise_callback_error()
                return None
        async with self._state_lock:
            if generation != self._active_generation or not self._active:
                raise OwnershipError("queued delivery belongs to a stale generation")
            self._in_flight = record
            self._delivery_completed.clear()
        return record

    def _raise_callback_error(self) -> None:
        if self._callback_error is not None:
            error = self._callback_error
            self._callback_error = None
            raise error

    async def checkpoint(self, record: StoredRecord) -> None:
        task = asyncio.current_task()
        assert task is not None
        async with self._checkpoint_lock:
            self._checkpoint_task = task
            try:
                self._require_owner()
                if record is not self._in_flight:
                    raise OwnershipError("record is not the current delivery")
                expected = self._cursor
                assert expected is not None
                cursor = ResumeCursor.last_successful(record.offset)
                generation = self._active_generation
                try:
                    if self._strategy is CheckpointStrategy.BROKER_MANAGED:
                        tracker = self._log._tracker
                        if tracker is None:
                            raise LifecycleError("checkpoint tracker is unavailable")
                        await self._log._within(
                            tracker.store_offset(
                                self._log._physical(
                                    self._key.stream, self._key.partition
                                ),
                                self._sac_name,
                                encode_cursor(cursor),
                            )
                        )
                        actual = await self._query_broker_cursor()
                        if actual != cursor:
                            raise RuntimeError(
                                "broker checkpoint verification mismatch"
                            )
                    else:
                        async with asyncio.timeout(self._log.options.operation_timeout):
                            await validate_checkpoint_store_call(
                                self._strategy.store.save(
                                    self._key, expected, cursor, self._owner
                                ),
                                cursor=cursor,
                                returns="none",
                            )
                except asyncio.CancelledError:
                    self._stopped = True
                    raise
                except CheckpointPersistenceError:
                    self._stopped = True
                    raise
                except BaseException as error:
                    self._stopped = True
                    raise CheckpointPersistenceError(cursor, error) from error
                async with self._state_lock:
                    if generation != self._active_generation or not self._active:
                        raise OwnershipError(
                            "checkpoint completed for a stale SAC generation"
                        )
                    self._cursor = cursor
                    self._in_flight = None
                    self._delivery_completed.set()
            finally:
                self._checkpoint_task = None

    async def stop(self) -> None:
        async with self._state_lock:
            self._intake_open = False
            self._stopped = True
            self._active = False
            self._active_generation += 1
            self._in_flight = None
            self._delivery_completed.set()
            self._clear_queue()
        async with asyncio.timeout(self._log.options.close_timeout):
            await self._unsubscribe()

    async def _quiesce(self) -> None:
        async with self._state_lock:
            self._intake_open = False
        await self._delivery_completed.wait()
        async with self._state_lock:
            self._stopped = True
            self._active = False
            self._active_generation += 1
            self._clear_queue()
        await self._unsubscribe()

    async def release(self) -> None:
        async with self._state_lock:
            if self._released:
                return
            self._released = True
            self._intake_open = False
            self._stopped = True
            self._active = False
            self._active_generation += 1
            self._in_flight = None
            self._delivery_completed.set()
            self._clear_queue()
        self._log._leases.pop(self._key, None)
        if not self._strategy_initialized:
            self._log._discard_strategy_reservation(self._key)
        async with asyncio.timeout(self._log.options.close_timeout):
            await self._unsubscribe()

    async def _unsubscribe(self) -> None:
        consumer, subscriber_id = self._consumer, self._subscriber_id
        self._consumer = None
        self._subscriber_id = None
        if consumer is not None:
            if subscriber_id is not None:
                await best_effort(consumer.unsubscribe(subscriber_id))
            await best_effort_close(consumer)

    async def _load_cursor(self) -> ResumeCursor | None:
        try:
            if self._strategy is CheckpointStrategy.BROKER_MANAGED:
                return await self._query_broker_cursor()
            async with asyncio.timeout(self._log.options.operation_timeout):
                await validate_checkpoint_store_call(
                    self._strategy.store.fence(self._key, self._owner),
                    cursor=None,
                    returns="none",
                )
                return await validate_checkpoint_store_call(
                    self._strategy.store.load(self._key),
                    cursor=None,
                    returns="optional_cursor",
                )
        except OffsetNotFound:
            return None
        except asyncio.CancelledError:
            raise
        except CheckpointPersistenceError:
            raise
        except BaseException as error:
            raise CheckpointPersistenceError(None, error) from error

    async def _query_broker_cursor(self) -> ResumeCursor:
        if not self._active:
            raise OwnershipError("broker cursor query requires active SAC ownership")
        tracker = self._log._tracker
        if tracker is None:
            raise LifecycleError("checkpoint tracker is unavailable")
        encoded = await self._log._within(
            tracker.query_offset(
                self._log._physical(self._key.stream, self._key.partition),
                self._sac_name,
            )
        )
        return decode_cursor(encoded)

    async def _create_cursor(
        self, cursor: ResumeCursor, generation: int
    ) -> ResumeCursor:
        try:
            if generation != self._active_generation or not self._active:
                raise OwnershipError("cursor initialization generation is stale")
            if self._strategy is CheckpointStrategy.BROKER_MANAGED:
                tracker = self._log._tracker
                if tracker is None:
                    raise LifecycleError("checkpoint tracker is unavailable")
                await self._log._within(
                    tracker.store_offset(
                        self._log._physical(self._key.stream, self._key.partition),
                        self._sac_name,
                        encode_cursor(cursor),
                    )
                )
                actual = await self._query_broker_cursor()
                if actual != cursor:
                    raise RuntimeError("broker checkpoint initialization mismatch")
                return actual
            async with asyncio.timeout(self._log.options.operation_timeout):
                created = await validate_checkpoint_store_call(
                    self._strategy.store.compare_and_create(
                        self._key, cursor, self._owner
                    ),
                    cursor=cursor,
                    returns="cursor",
                )
                assert created is not None
                return created
        except asyncio.CancelledError:
            raise
        except CheckpointPersistenceError:
            raise
        except BaseException as error:
            raise CheckpointPersistenceError(cursor, error) from error

    async def _resolve_start(self) -> int:
        start = self._subscription.start
        if isinstance(start, Beginning):
            return await self._log._earliest(self._key.stream, self._key.partition)
        if isinstance(start, ExactOffset):
            return start.offset
        raise ValidationError("start position is not supported")

    async def _require_retained(self, offset: int) -> None:
        earliest = await self._log._earliest(self._key.stream, self._key.partition)
        if offset < earliest:
            raise RetentionGapError(
                self._key.stream,
                self._key.partition,
                requested_offset=offset,
                bounds=AvailableBounds(earliest, earliest),
                group=self._key.group,
            )

    async def _require_retained_after_subscription(self) -> None:
        if self._active and self._cursor is not None:
            await self._require_retained(self._cursor.offset)

    def _require_owner(self) -> None:
        if (
            self._released
            or self._stopped
            or not self._active
            or self._log._leases.get(self._key) is not self
        ):
            raise OwnershipError("partition lease is not current")


__all__ = ["RabbitMqPartitionLease"]
