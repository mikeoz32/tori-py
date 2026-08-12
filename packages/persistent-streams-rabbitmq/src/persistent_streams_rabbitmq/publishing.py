from __future__ import annotations

import asyncio
from typing import Any

from persistent_streams import (
    AppendRequest,
    InvalidPartitionError,
    LifecycleError,
    PublishingConflictError,
    PublishOutcome,
    PublishReceipt,
    ResourceLimitError,
    StalePublishingIdError,
    StreamDefinition,
    ValidationError,
)
from persistent_streams.validation import validate_append_request_limits
from rstream import Producer
from rstream.recovery import BackOffRecoveryStrategy

from persistent_streams_rabbitmq._envelope import RecordEnvelope, encode_amqp_message
from persistent_streams_rabbitmq._shared import best_effort_close, envelope_limits
from persistent_streams_rabbitmq._state import PublisherSlot
from persistent_streams_rabbitmq.options import RabbitMqPersistentStreamsOptions


class PublishingMixin:
    options: RabbitMqPersistentStreamsOptions
    _producer: Producer | None
    _publisher_slots: dict[tuple[str, str | None], PublisherSlot]
    _producer_coordinates: dict[tuple[str, int, str], tuple[int, AppendRequest]]
    _pending: set[int]
    _pending_bytes: int
    _admission_lock: asyncio.Lock
    _resource_lock: asyncio.Lock
    _resource_generation: int
    _failed: bool

    async def append(self, stream: str, request: AppendRequest) -> PublishReceipt:
        self._require_available()
        definition = self._definition(stream)
        validate_append_request_limits(definition, request)
        partition = definition.router.route(
            bytes(request.partition_key), definition.partition_count
        )
        if (
            isinstance(partition, bool)
            or not isinstance(partition, int)
            or not 0 <= partition < definition.partition_count
        ):
            raise InvalidPartitionError("router returned an invalid partition")
        physical = self._physical(stream, partition)
        envelope = RecordEnvelope(
            request.record_id,
            bytes(request.partition_key),
            {name: bytes(value) for name, value in request.headers.items()},
            bytes(request.payload),
        )
        message = encode_amqp_message(envelope, envelope_limits(definition))
        try:
            producer_name_bytes = (
                b""
                if request.producer_name is None
                else request.producer_name.encode("utf-8", "strict")
            )
        except UnicodeEncodeError as error:
            raise ValidationError("producer_name must be valid UTF-8") from error
        if len(producer_name_bytes) > 255:
            raise ValidationError("producer_name exceeds the protocol string limit")
        if request.publishing_id is not None:
            if request.publishing_id == 0:
                raise ValidationError("RabbitMQ named publishing IDs must start at one")
            message.publishing_id = request.publishing_id
        size = len(bytes(message)) + 64
        if size > self.options.connection.frame_max:
            raise ResourceLimitError("encoded AMQP message exceeds frame_max")
        marker = id(message)
        async with self._admission_lock:
            if (
                len(self._pending) >= self.options.max_pending_count
                or self._pending_bytes + size > self.options.max_pending_bytes
            ):
                return PublishReceipt(
                    request.record_id,
                    partition,
                    PublishOutcome.BACKPRESSURED,
                    ("local-admission-rejected",),
                )
            self._pending.add(marker)
            self._pending_bytes += size
        try:
            slot = await self._publisher_slot((physical, request.producer_name))
            async with slot.lock:
                return await self._append_locked(
                    stream, partition, physical, request, message, slot
                )
        finally:
            async with self._admission_lock:
                self._pending.discard(marker)
                self._pending_bytes -= size

    async def _append_locked(
        self,
        stream: str,
        partition: int,
        physical: str,
        request: AppendRequest,
        message: Any,
        slot: PublisherSlot,
    ) -> PublishReceipt:
        if request.producer_name is not None:
            coordinate = (stream, partition, request.producer_name)
            local = self._producer_coordinates.get(coordinate)
            if (
                local is not None
                and request.publishing_id is not None
                and request.publishing_id < local[0]
            ):
                raise StalePublishingIdError("publishing ID is stale")
            if local is not None and local[0] == request.publishing_id:
                if local[1] != request:
                    raise PublishingConflictError("publishing ID request differs")
                return PublishReceipt(
                    request.record_id,
                    partition,
                    PublishOutcome.DEDUPLICATED,
                    ("local-confirmed-publisher-coordinate",),
                )
            sequence = await self.query_publisher_sequence(
                stream, partition, request.producer_name
            )
            assert request.publishing_id is not None
            if sequence > request.publishing_id:
                raise StalePublishingIdError("publishing ID is stale")
            if sequence == request.publishing_id:
                return PublishReceipt(
                    request.record_id,
                    partition,
                    PublishOutcome.INDETERMINATE,
                    (
                        "broker-sequence-exists",
                        "cross-restart-content-association-unsupported",
                    ),
                )
        try:
            await asyncio.wait_for(
                (await self._publisher(slot, request.producer_name)).send_wait(
                    physical,
                    message,
                    publisher_name=request.producer_name,
                    timeout=max(1, int(self.options.confirm_timeout)),
                ),
                self.options.confirm_timeout,
            )
        except TimeoutError:
            return PublishReceipt(
                request.record_id,
                partition,
                PublishOutcome.TIMED_OUT,
                ("confirm-deadline-expired", "acceptance-indeterminate"),
            )
        except Exception as error:
            return PublishReceipt(
                request.record_id,
                partition,
                PublishOutcome.INDETERMINATE,
                (type(error).__name__, "acceptance-indeterminate"),
            )
        receipt = PublishReceipt(
            request.record_id,
            partition,
            PublishOutcome.CONFIRMED,
            ("rabbitmq-stream-confirmed",),
        )
        if request.producer_name is not None:
            assert request.publishing_id is not None
            self._producer_coordinates[(stream, partition, request.producer_name)] = (
                request.publishing_id,
                request,
            )
        return receipt

    async def _publisher(self, slot: PublisherSlot, name: str | None) -> Producer:
        if name is None:
            if self._producer is None:
                raise LifecycleError("base producer is unavailable")
            return self._producer
        if slot.producer is not None:
            return slot.producer
        async with self._resource_lock:
            if slot.producer is not None:
                return slot.producer
            generation = self._resource_generation
            producer = Producer(
                **self.options.connection.driver_kwargs(),
                on_close_handler=self._close_callback(generation),
                recovery_strategy=BackOffRecoveryStrategy(False),
            )
            try:
                await self._within(producer.start())
            except BaseException:
                await best_effort_close(producer)
                raise
            if generation != self._resource_generation or self._failed:
                await best_effort_close(producer)
                raise LifecycleError("RabbitMQ resource generation changed")
            slot.producer = producer
            return producer

    async def _publisher_slot(
        self, coordinate: tuple[str, str | None]
    ) -> PublisherSlot:
        async with self._resource_lock:
            slot = self._publisher_slots.get(coordinate)
            if slot is not None:
                return slot
            if (
                coordinate[1] is not None
                and sum(name is not None for _, name in self._publisher_slots)
                >= self.options.max_named_producers
            ):
                raise ResourceLimitError("named producer resource limit reached")
            slot = PublisherSlot()
            self._publisher_slots[coordinate] = slot
            return slot

    async def query_publisher_sequence(
        self, stream: str, partition: int, producer_name: str
    ) -> int:
        self._partition(self._definition(stream), partition)
        metadata = self._require_metadata()
        return await self._within(
            metadata.query_publisher_sequence(
                self._physical(stream, partition), producer_name
            )
        )

    def _close_callback(self, generation: int):
        raise NotImplementedError

    def _definition(self, stream: str) -> StreamDefinition:
        raise NotImplementedError

    def _physical(self, stream: str, partition: int) -> str:
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


__all__ = ["PublishingMixin"]
