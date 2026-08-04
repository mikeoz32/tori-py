"""Inbound RabbitMQ server transport with explicit message settlement."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from nestpy_microservices.errors import (
    DuplicateSettlementError,
    TransportStateError,
)
from nestpy_microservices.identities import ReplyRoute, ServiceIdentity, utc_now
from nestpy_microservices.invocation import (
    InvocationCompletion,
    SettlementRecommendation,
)
from nestpy_microservices.rabbitmq.connection import RabbitMqConnectionManager
from nestpy_microservices.rabbitmq.publisher import RabbitMqPublisher
from nestpy_microservices.rabbitmq.topology import (
    RabbitMqTopology,
    compile_event_topology,
    compile_rpc_topology,
    merge_topologies,
)
from nestpy_microservices.transport import (
    DeliveryDispatcher,
    EncodedDelivery,
    EventSubscription,
    Publication,
    PublicationReceipt,
    ServerTransport,
    TransportStatus,
    TransportStatusEvent,
)


class RabbitMqServerTransport(ServerTransport):
    """One RabbitMQ service endpoint using manual ACK/NACK settlement."""

    def __init__(
        self,
        manager: RabbitMqConnectionManager,
        service: ServiceIdentity,
        *,
        prefetch: int = 1,
    ) -> None:
        if not isinstance(prefetch, int) or prefetch <= 0:
            raise ValueError("prefetch must be positive")
        self.manager = manager
        self.service = service
        self.prefetch = prefetch
        self._status = TransportStatus.CREATED
        self._status_events: asyncio.Queue[TransportStatusEvent] = asyncio.Queue()
        self._queues: dict[str, Any] = {}
        self._consumer_tags: dict[str, str] = {}
        self._deliveries: dict[int, Any] = {}
        self._dispatcher: DeliveryDispatcher | None = None
        self._publisher = RabbitMqPublisher(manager)

    @property
    def status(self) -> TransportStatus:
        return self._status

    async def prepare(
        self,
        *,
        rpc_methods: Iterable[str] = (),
        subscriptions: Iterable[EventSubscription] = (),
    ) -> None:
        self._require(TransportStatus.CREATED)
        rpc_methods = tuple(rpc_methods)
        subscriptions = tuple(subscriptions)
        topologies: list[RabbitMqTopology] = []
        if rpc_methods:
            topologies.append(compile_rpc_topology(self.service))
        topologies.extend(compile_event_topology(item) for item in subscriptions)
        if not topologies:
            raise ValueError("RabbitMQ server requires RPC methods or subscriptions")
        self._queues = await self.manager.declare(merge_topologies(*topologies))
        self._set_status(TransportStatus.PREPARED)

    async def start(self, dispatcher: DeliveryDispatcher) -> None:
        self._require(TransportStatus.PREPARED)
        self._dispatcher = dispatcher
        try:
            consumer_channel: Any = self.manager.channels.consumer
            await consumer_channel.set_qos(prefetch_count=self.prefetch)
            for queue_name, queue in self._queues.items():
                tag = f"nestpy.{self.service.label}.{len(self._consumer_tags)}"
                await queue.consume(
                    self._on_message,
                    consumer_tag=tag,
                    no_ack=False,
                )
                self._consumer_tags[queue_name] = tag
        except Exception:
            await self.stop_intake()
            raise
        self._set_status(TransportStatus.RUNNING)

    async def settle(
        self, delivery: EncodedDelivery, outcome: SettlementRecommendation
    ) -> None:
        if not isinstance(outcome, SettlementRecommendation):
            raise ValueError("unsupported settlement recommendation")
        message = self._deliveries.pop(id(delivery), None)
        if message is None:
            raise DuplicateSettlementError("delivery was already settled")
        if outcome is SettlementRecommendation.ACK:
            await message.ack()
        elif outcome is SettlementRecommendation.RETRY:
            await message.nack(requeue=True)
        else:
            await message.reject(requeue=False)

    async def publish_reply(self, publication: Publication) -> PublicationReceipt:
        self._require_open()
        return await self._publisher.publish(publication)

    async def stop_intake(self) -> None:
        if self._status in {TransportStatus.CREATED, TransportStatus.CLOSED}:
            return
        if self._status is TransportStatus.QUIESCING:
            return
        self._set_status(TransportStatus.QUIESCING)
        for queue_name, tag in tuple(self._consumer_tags.items()):
            await self._queues[queue_name].cancel(tag)
        self._consumer_tags.clear()

    async def close(self) -> None:
        if self._status is TransportStatus.CLOSED:
            return
        if self._status in {TransportStatus.PREPARED, TransportStatus.RUNNING}:
            await self.stop_intake()
        self._deliveries.clear()
        self._set_status(TransportStatus.CLOSED)

    async def statuses(self) -> AsyncIterator[TransportStatusEvent]:
        while True:
            event = await self._status_events.get()
            yield event
            if event.status is TransportStatus.CLOSED:
                return

    def unwrap(self) -> object:
        return self.manager

    async def _on_message(self, message: Any) -> None:
        delivery = _decode_message(message)
        self._deliveries[id(delivery)] = message
        dispatcher = self._dispatcher
        if dispatcher is None:
            await self.settle(delivery, SettlementRecommendation.RETRY)
            return
        try:
            result = await dispatcher(delivery)
            outcome = (
                result.recommendation
                if isinstance(result, InvocationCompletion)
                else result
            )
            if not isinstance(outcome, SettlementRecommendation):
                outcome = SettlementRecommendation.REJECT
        except asyncio.CancelledError:
            raise
        except Exception:
            outcome = SettlementRecommendation.RETRY
        await self.settle(delivery, outcome)

    def _set_status(self, status: TransportStatus, detail: str = "") -> None:
        self._status = status
        self._status_events.put_nowait(
            TransportStatusEvent(status, datetime.now(UTC), detail)
        )

    def _require(self, expected: TransportStatus) -> None:
        if self._status is not expected:
            raise TransportStateError(
                f"expected {expected.value}, got {self._status.value}"
            )

    def _require_open(self) -> None:
        if self._status not in {
            TransportStatus.PREPARED,
            TransportStatus.RUNNING,
            TransportStatus.QUIESCING,
        }:
            raise TransportStateError("server transport is not available")


def _decode_message(message: Any) -> EncodedDelivery:
    headers = message.headers if isinstance(message.headers, dict) else {}
    attempt = headers.get("x-attempt", 1)
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0:
        attempt = 1
    return EncodedDelivery(
        message_id=_message_uuid(message.message_id),
        routing_key=message.routing_key,
        body=message.body,
        headers=headers,
        received_at=utc_now(),
        attempt=attempt,
        redelivered=bool(message.redelivered),
        correlation_id=_optional_uuid(message.correlation_id),
        reply_to=_reply_route(message.reply_to),
        native=message,
    )


def _message_uuid(value: object) -> UUID:
    return _optional_uuid(value) or uuid4()


def _optional_uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _reply_route(value: object) -> ReplyRoute | None:
    if not isinstance(value, str):
        return None
    try:
        return ReplyRoute(value)
    except ValueError:
        return None


__all__ = ["RabbitMqServerTransport"]
