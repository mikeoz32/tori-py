"""Outbound RabbitMQ client transport for RPC, events, and replies."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from nestpy_microservices.errors import (
    TransportCapacityError,
    TransportCorrelationError,
    TransportStateError,
)
from nestpy_microservices.identities import (
    EventIdentity,
    ReplyRoute,
    RpcTarget,
    utc_now,
)
from nestpy_microservices.rabbitmq.connection import RabbitMqConnectionManager
from nestpy_microservices.rabbitmq.publisher import RabbitMqPublisher
from nestpy_microservices.rabbitmq.server import _decode_message
from nestpy_microservices.rabbitmq.topology import compile_reply_topology
from nestpy_microservices.transport import (
    ClientTransport,
    EncodedDelivery,
    Publication,
    PublicationReceipt,
    TransportStatus,
    TransportStatusEvent,
)


class RabbitMqClientTransport(ClientTransport):
    """One bounded-reply RabbitMQ client endpoint."""

    def __init__(
        self,
        manager: RabbitMqConnectionManager,
        *,
        reply_to: ReplyRoute | None = None,
        max_pending_replies: int = 10_000,
    ) -> None:
        if not isinstance(max_pending_replies, int) or max_pending_replies <= 0:
            raise ValueError("max_pending_replies must be positive")
        self.manager = manager
        self._reply_to = reply_to or ReplyRoute.generate()
        self.max_pending_replies = max_pending_replies
        self._status = TransportStatus.CREATED
        self._status_events: asyncio.Queue[TransportStatusEvent] = asyncio.Queue()
        self._reply_queue: asyncio.Queue[EncodedDelivery | None] = asyncio.Queue(
            maxsize=max_pending_replies
        )
        self._reply_consumer: Any | None = None
        self._consumer_tag: str | None = None
        self._pending: set[UUID] = set()
        self._completed: deque[UUID] = deque(maxlen=max_pending_replies)
        self._publisher = RabbitMqPublisher(manager)

    @property
    def status(self) -> TransportStatus:
        return self._status

    @property
    def reply_to(self) -> ReplyRoute:
        return self._reply_to

    async def start(self) -> None:
        if self._status is not TransportStatus.CREATED:
            raise TransportStateError("client transport has already started")
        queues = await self.manager.declare(compile_reply_topology(self.reply_to.value))
        queue = queues[self.reply_to.value]
        self._reply_consumer = queue
        route_name = self.reply_to.value.removeprefix("reply.")
        self._consumer_tag = f"nestpy.reply.{route_name}"
        await queue.consume(
            self._on_reply,
            consumer_tag=self._consumer_tag,
            no_ack=False,
        )
        self._set_status(TransportStatus.RUNNING)

    async def publish_rpc(
        self, target: RpcTarget, publication: Publication
    ) -> PublicationReceipt:
        self._require_running()
        if publication.routing_key != target.routing_key:
            raise ValueError("publication routing key does not match RPC target")
        correlation_id = publication.correlation_id
        if correlation_id is None or publication.reply_to != self.reply_to:
            raise TransportCorrelationError(
                "RPC publications require this client's reply route and "
                "a correlation ID"
            )
        self._reserve(correlation_id)
        try:
            return await self._publisher.publish(
                _with_publication(publication, mandatory=True)
            )
        except Exception:
            self._pending.discard(correlation_id)
            raise

    async def publish_event(
        self, identity: EventIdentity, publication: Publication
    ) -> PublicationReceipt:
        self._require_running()
        if publication.routing_key != identity.routing_key:
            raise ValueError("publication routing key does not match event identity")
        return await self._publisher.publish(
            _with_publication(
                publication,
                native=(identity.exchange_name, identity.routing_key),
            )
        )

    async def replies(self) -> AsyncIterator[EncodedDelivery]:
        self._require_running()
        while self._status is TransportStatus.RUNNING:
            reply = await self._reply_queue.get()
            if reply is None:
                return
            correlation_id = reply.correlation_id
            if correlation_id is None:
                continue
            if correlation_id in self._completed:
                continue
            if correlation_id not in self._pending:
                continue
            self._pending.remove(correlation_id)
            self._completed.append(correlation_id)
            yield reply

    async def close(self) -> None:
        if self._status is TransportStatus.CLOSED:
            return
        if self._reply_consumer is not None and self._consumer_tag is not None:
            await self._reply_consumer.cancel(self._consumer_tag)
        self._reply_consumer = None
        self._consumer_tag = None
        self._set_status(TransportStatus.CLOSED)
        while not self._reply_queue.empty():
            self._reply_queue.get_nowait()
        self._reply_queue.put_nowait(None)

    def cancel_pending(self, correlation_id: UUID) -> None:
        self._pending.discard(correlation_id)

    async def statuses(self) -> AsyncIterator[TransportStatusEvent]:
        while True:
            event = await self._status_events.get()
            yield event
            if event.status is TransportStatus.CLOSED:
                return

    def unwrap(self) -> object:
        return self.manager

    async def _on_reply(self, message: Any) -> None:
        delivery = _decode_message(message)
        await self._reply_queue.put(delivery)
        await message.ack()

    def _reserve(self, correlation_id: UUID) -> None:
        if correlation_id in self._pending or correlation_id in self._completed:
            raise TransportCorrelationError("RPC correlation was already used")
        if len(self._pending) >= self.max_pending_replies:
            raise TransportCapacityError("pending reply map is full")
        self._pending.add(correlation_id)

    def _set_status(self, status: TransportStatus) -> None:
        self._status = status
        self._status_events.put_nowait(TransportStatusEvent(status, utc_now()))

    def _require_running(self) -> None:
        if self._status is not TransportStatus.RUNNING:
            raise TransportStateError("client transport is not running")


def _with_publication(
    publication: Publication,
    *,
    mandatory: bool | None = None,
    native: object | None = None,
) -> Publication:
    return Publication(
        message_id=publication.message_id,
        routing_key=publication.routing_key,
        body=publication.body,
        headers=publication.headers,
        mandatory=publication.mandatory if mandatory is None else mandatory,
        correlation_id=publication.correlation_id,
        reply_to=publication.reply_to,
        native=native,
        expires_at=publication.expires_at,
    )


__all__ = ["RabbitMqClientTransport"]
