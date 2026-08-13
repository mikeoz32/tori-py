from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import UUID, uuid4

from rstream import Consumer, ConsumerOffsetSpecification, OffsetType
from rstream.consumer import MessageContext
from tori_py_persistent_streams_core import (
    AvailableBounds,
    RecordPage,
    ResourceLimitError,
    RetentionGapError,
    StoredRecord,
    StreamDefinition,
    ValidationError,
)

from tori_py_persistent_streams_rabbitmq._envelope import (
    EnvelopeKind,
    EnvelopeLimits,
    RecordEnvelope,
    encode_amqp_message,
)
from tori_py_persistent_streams_rabbitmq._shared import (
    best_effort,
    best_effort_close,
    decode_message,
    envelope_limits,
    safe_amqp_decoder,
    stored_record,
)
from tori_py_persistent_streams_rabbitmq._state import PublisherSlot
from tori_py_persistent_streams_rabbitmq.options import RabbitMqPersistentStreamsOptions


class ReadingMixin:
    options: RabbitMqPersistentStreamsOptions

    async def bounds(self, stream: str, partition: int) -> AvailableBounds | None:
        self._require_available()
        definition = self._definition(stream)
        self._partition(definition, partition)
        return None

    async def _earliest(self, stream: str, partition: int) -> int:
        stats = await self._within(
            self._require_metadata().stream_stats(self._physical(stream, partition))
        )
        return max(stats["first_chunk_id"], 0)

    async def _write_barrier(self, physical: str) -> UUID:
        barrier_id = uuid4()
        message = encode_amqp_message(
            RecordEnvelope(
                barrier_id,
                b"_psrm",
                {},
                b"",
                kind=EnvelopeKind.BARRIER,
            )
        )
        slot = await self._publisher_slot((physical, None))
        async with slot.lock:
            await asyncio.wait_for(
                (await self._publisher(slot, None)).send_wait(
                    physical,
                    message,
                    timeout=max(1, int(self.options.confirm_timeout)),
                ),
                self.options.confirm_timeout,
            )
        return barrier_id

    async def read(
        self, stream: str, partition: int, from_offset: int, limit: int
    ) -> RecordPage:
        self._require_available()
        definition = self._definition(stream)
        self._partition(definition, partition)
        if (
            isinstance(from_offset, bool)
            or not isinstance(from_offset, int)
            or from_offset < 0
        ):
            raise ValidationError("from_offset must be non-negative")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValidationError("limit must be positive")
        if limit > definition.limits.max_read_records:
            raise ResourceLimitError("read limit exceeds stream limit")
        earliest = await self._earliest(stream, partition)
        if from_offset < earliest:
            raise RetentionGapError(
                stream,
                partition,
                requested_offset=from_offset,
                bounds=AvailableBounds(earliest, earliest),
            )
        physical = self._physical(stream, partition)
        barrier_id = await self._write_barrier(physical)
        records = await self._collect(
            physical,
            stream,
            partition,
            from_offset,
            limit,
            envelope_limits(definition),
            barrier_id,
        )
        return RecordPage(records, None)

    async def _collect(
        self,
        physical: str,
        logical: str,
        partition: int,
        from_offset: int,
        limit: int,
        limits: EnvelopeLimits,
        barrier_id: UUID,
    ) -> tuple[StoredRecord, ...]:
        queue: asyncio.Queue[StoredRecord | BaseException | None] = asyncio.Queue(
            maxsize=min(limit, self.options.callback_queue_capacity)
        )
        consumer = Consumer(**self.options.connection.driver_kwargs())
        accepted = 0
        range_checked = asyncio.Event()

        async def callback(message: object, context: MessageContext) -> None:
            nonlocal accepted
            try:
                await range_checked.wait()
                if context.offset < from_offset:
                    return
                envelope = decode_message(message, limits)
                if envelope.kind is EnvelopeKind.BARRIER:
                    if envelope.record_id == barrier_id:
                        await queue.put(None)
                    return
                if accepted >= limit:
                    return
                value: StoredRecord | BaseException | None = stored_record(
                    envelope, context, logical, partition
                )
                accepted += 1
            except BaseException as error:
                value = error
            await queue.put(value)

        await self._within(consumer.start())
        subscriber_id: int | None = None
        records: list[StoredRecord] = []
        boundary_observed = False
        try:
            subscriber_id = await self._within(
                consumer.subscribe(
                    physical,
                    cast(Any, callback),
                    decoder=safe_amqp_decoder,
                    offset_specification=ConsumerOffsetSpecification(
                        OffsetType.OFFSET, from_offset
                    ),
                    initial_credit=self.options.initial_credit,
                )
            )
            await self._after_read_subscribe(physical, from_offset)
            retained = await self._earliest(logical, partition)
            if from_offset < retained:
                raise RetentionGapError(
                    logical,
                    partition,
                    requested_offset=from_offset,
                    bounds=AvailableBounds(retained, retained),
                )
            range_checked.set()
            deadline = (
                asyncio.get_running_loop().time() + self.options.operation_timeout
            )
            while len(records) < limit:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    value = await asyncio.wait_for(queue.get(), remaining)
                except TimeoutError:
                    break
                if isinstance(value, BaseException):
                    raise value
                if value is None:
                    boundary_observed = True
                    break
                records.append(value)
        finally:
            if subscriber_id is not None:
                await best_effort(consumer.unsubscribe(subscriber_id))
            await best_effort_close(consumer)
        if len(records) < limit and not boundary_observed:
            raise TimeoutError("read snapshot barrier was not observed")
        return tuple(records)

    async def _after_read_subscribe(self, physical: str, from_offset: int) -> None:
        """Deterministic seam for retention races after native subscription."""
        del physical, from_offset

    def _definition(self, stream: str) -> StreamDefinition:
        raise NotImplementedError

    def _physical(self, stream: str, partition: int) -> str:
        raise NotImplementedError

    def _publisher_slot(self, coordinate: tuple[str, str | None]):
        raise NotImplementedError

    def _publisher(self, slot: PublisherSlot, name: str | None):
        raise NotImplementedError

    def _require_available(self) -> None:
        raise NotImplementedError

    def _require_metadata(self):
        raise NotImplementedError

    @staticmethod
    def _partition(definition: StreamDefinition, partition: int) -> None:
        raise NotImplementedError

    async def _within(self, operation):
        raise NotImplementedError


__all__ = ["ReadingMixin"]
