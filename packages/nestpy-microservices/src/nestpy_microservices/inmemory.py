"""Deterministic, process-local transport implementations for MS4."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from nestpy_microservices.errors import (
    DuplicateSettlementError,
    TransportCapacityError,
    TransportCorrelationError,
    TransportError,
    TransportStateError,
    TransportUnroutableError,
)
from nestpy_microservices.identities import (
    EventIdentity,
    ReplyRoute,
    RpcTarget,
    ServiceIdentity,
    utc_now,
)
from nestpy_microservices.invocation import (
    InvocationCompletion,
    SettlementRecommendation,
)
from nestpy_microservices.transport import (
    DeliveryDispatcher,
    EncodedDelivery,
    EventSubscription,
    Publication,
    PublicationReceipt,
    TransportStatus,
    TransportStatusEvent,
)


@dataclass(slots=True)
class _QueuedPublication:
    publication: Publication
    attempt: int = 1
    redelivered: bool = False


@dataclass(slots=True)
class _DeliveryRecord:
    server: InMemoryServerTransport
    queue_name: str
    delivery: EncodedDelivery
    queued: _QueuedPublication
    settled: bool = False


@dataclass(slots=True)
class _Consumer:
    server: InMemoryServerTransport
    prefetch: int
    in_flight: int = 0
    active: bool = True


@dataclass(slots=True)
class _Queue:
    name: str
    messages: deque[_QueuedPublication] = field(default_factory=deque)
    consumers: dict[str, _Consumer] = field(default_factory=dict)
    deliveries: dict[int, _DeliveryRecord] = field(default_factory=dict)
    cursor: int = 0
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


class InMemoryBroker:
    """A bounded broker with explicit queues, bindings, and manual settlement."""

    def __init__(
        self,
        *,
        max_queue_messages: int = 10_000,
        max_delivery_attempts: int = 5,
    ) -> None:
        if not isinstance(max_queue_messages, int) or max_queue_messages <= 0:
            raise ValueError("max_queue_messages must be positive")
        if not isinstance(max_delivery_attempts, int) or max_delivery_attempts <= 0:
            raise ValueError("max_delivery_attempts must be positive")
        self.max_queue_messages = max_queue_messages
        self.max_delivery_attempts = max_delivery_attempts
        self.dead_letters: deque[EncodedDelivery] = deque(maxlen=max_queue_messages)
        self._queues: dict[str, _Queue] = {}
        self._rpc_queues: dict[str, str] = {}
        self._event_routes: dict[tuple[str, str], set[str]] = {}
        self._reply_queues: dict[str, asyncio.Queue[EncodedDelivery | None]] = {}
        self._servers: set[InMemoryServerTransport] = set()
        self._clients: set[InMemoryClientTransport] = set()
        self._ephemeral_queues: set[str] = set()
        self._reliable_broadcast_owners: dict[str, InMemoryServerTransport] = {}
        self._closed = False

    async def register_server(
        self,
        server: InMemoryServerTransport,
        *,
        rpc_methods: Iterable[str],
        subscriptions: Iterable[EventSubscription],
    ) -> None:
        self._require_open()
        owner = self._servers_by_replica(server.replica_id)
        if owner is not None and owner is not server:
            raise TransportStateError("replica_id is already registered")
        rpc_methods = tuple(rpc_methods)
        subscriptions = tuple(subscriptions)
        for method in rpc_methods:
            if not isinstance(method, str) or not method:
                raise ValueError("RPC methods must be non-empty strings")
        event_queues = tuple(
            _event_queue_name(subscription) for subscription in subscriptions
        )
        for subscription, event_queue in zip(subscriptions, event_queues, strict=True):
            if subscription.mode == "broadcast" and subscription.reliable:
                owner = self._reliable_broadcast_owners.get(event_queue)
                if owner is not None and owner is not server:
                    raise TransportStateError(
                        "reliable broadcast instance identity is already active"
                    )
        self._servers.add(server)
        queue_name = f"rpc.{server.service.label}"
        self._queues.setdefault(queue_name, _Queue(queue_name))
        self._rpc_queues[server.service.label] = queue_name
        server._queue_names.add(queue_name)
        for subscription, event_queue in zip(subscriptions, event_queues, strict=True):
            if subscription.mode == "broadcast" and subscription.reliable:
                owner = self._reliable_broadcast_owners.get(event_queue)
                if owner is not None and owner is not server:
                    raise TransportStateError(
                        "reliable broadcast instance identity is already active"
                    )
                self._reliable_broadcast_owners[event_queue] = server
            if subscription.mode == "broadcast" and not subscription.reliable:
                self._ephemeral_queues.add(event_queue)
            self._queues.setdefault(event_queue, _Queue(event_queue))
            self._event_routes.setdefault(
                (
                    subscription.identity.exchange_name,
                    subscription.identity.routing_key,
                ),
                set(),
            ).add(event_queue)
            server._queue_names.add(event_queue)
            server._subscriptions_by_queue[event_queue] = subscription

    async def register_reply_route(
        self,
        route: ReplyRoute,
        client: InMemoryClientTransport | None = None,
        *,
        max_pending_replies: int = 10_000,
    ) -> asyncio.Queue[EncodedDelivery | None]:
        self._require_open()
        if route.value in self._reply_queues:
            raise TransportStateError("reply route is already registered")
        queue: asyncio.Queue[EncodedDelivery | None] = asyncio.Queue(
            maxsize=max_pending_replies
        )
        self._reply_queues[route.value] = queue
        if client is not None:
            self._clients.add(client)
        return queue

    async def unregister_reply_route(
        self, route: ReplyRoute, client: InMemoryClientTransport | None = None
    ) -> None:
        queue = self._reply_queues.pop(route.value, None)
        if queue is not None:
            _signal_reply_queue_closed(queue)
        if client is not None:
            self._clients.discard(client)

    async def start_server(self, server: InMemoryServerTransport) -> None:
        for name in server._queue_names:
            queue = self._queues[name]
            queue.consumers[server.replica_id] = _Consumer(server, server.prefetch)
            if queue.task is None or queue.task.done():
                queue.task = asyncio.create_task(self._run_queue(queue))
            queue.wake.set()

    async def stop_server(
        self, server: InMemoryServerTransport, *, requeue: bool = True
    ) -> None:
        for queue in tuple(self._queues.values()):
            consumer = queue.consumers.pop(server.replica_id, None)
            if consumer is not None:
                consumer.active = False
            for key, record in tuple(queue.deliveries.items()):
                if requeue and record.server is server and not record.settled:
                    queue.deliveries.pop(key)
                    server._delivery_queues.pop(id(record.delivery), None)
                    record.queued.attempt += 1
                    record.queued.redelivered = True
                    queue.messages.appendleft(record.queued)
                    if consumer is not None:
                        consumer.in_flight -= 1
                    server._in_flight -= 1
            queue.wake.set()
            other_owner = any(
                other is not server and queue.name in other._queue_names
                for other in self._servers
            )
            if (
                requeue
                and queue.name in self._ephemeral_queues
                and not queue.consumers
                and not other_owner
            ):
                await self._remove_queue(queue.name)
            elif self._reliable_broadcast_owners.get(queue.name) is server:
                self._reliable_broadcast_owners.pop(queue.name, None)

    async def settle(
        self,
        server: InMemoryServerTransport,
        delivery: EncodedDelivery,
        outcome: SettlementRecommendation,
    ) -> None:
        if not isinstance(outcome, SettlementRecommendation):
            raise ValueError("unsupported settlement recommendation")
        queue_name = server._delivery_queues.get(id(delivery))
        if queue_name is None:
            raise DuplicateSettlementError("delivery was already settled")
        queue = self._queues[queue_name]
        record = queue.deliveries.get(id(delivery))
        if record is None or record.settled:
            raise DuplicateSettlementError("delivery was already settled")
        redelivery_requested = outcome in {
            SettlementRecommendation.RETRY,
            SettlementRecommendation.UNSETTLED,
        }
        retry_terminal = (
            redelivery_requested
            and record.queued.attempt < self.max_delivery_attempts
            and len(queue.messages) >= self.max_queue_messages
        )
        server._delivery_queues.pop(id(delivery), None)
        queue.deliveries.pop(id(delivery), None)
        record.settled = True
        consumer = queue.consumers.get(server.replica_id)
        if consumer is not None:
            consumer.in_flight -= 1
        server._in_flight -= 1
        if (
            redelivery_requested
            and record.queued.attempt < self.max_delivery_attempts
            and not retry_terminal
        ):
            retry = record.queued
            retry.attempt += 1
            retry.redelivered = True
            queue.messages.append(retry)
        elif redelivery_requested:
            self.dead_letters.append(delivery)
        self._wake_server_queues(server)

    async def publish(self, publication: Publication) -> PublicationReceipt:
        self._require_open()
        routes = self._routes(publication.routing_key, publication.native)
        if publication.mandatory and not routes:
            raise TransportUnroutableError(
                f"no route for publication {publication.routing_key!r}"
            )
        if any(
            len(self._queues[name].messages) >= self.max_queue_messages
            for name in routes
        ):
            raise TransportCapacityError("one or more in-memory queues are full")
        queued = _QueuedPublication(publication)
        for name in routes:
            queue = self._queues[name]
            queue.messages.append(
                _QueuedPublication(
                    publication=queued.publication,
                    attempt=queued.attempt,
                    redelivered=queued.redelivered,
                )
            )
            queue.wake.set()
        return PublicationReceipt(publication.message_id, utc_now(), bool(routes))

    async def publish_reply(self, publication: Publication) -> PublicationReceipt:
        self._require_open()
        if publication.correlation_id is None:
            raise TransportCorrelationError("RPC replies require a correlation ID")
        route = publication.routing_key
        target = self._reply_queues.get(route)
        if target is None:
            raise TransportUnroutableError(f"reply route {route!r} does not exist")
        try:
            target.put_nowait(
                EncodedDelivery(
                    message_id=publication.message_id,
                    routing_key=route,
                    body=publication.body,
                    headers=publication.headers,
                    received_at=utc_now(),
                    correlation_id=publication.correlation_id,
                    reply_to=publication.reply_to,
                    native=publication.native,
                )
            )
        except asyncio.QueueFull as error:
            raise TransportCapacityError("reply queue is full") from error
        return PublicationReceipt(publication.message_id, utc_now(), True)

    async def close(self) -> None:
        if self._closed:
            return
        for server in tuple(self._servers):
            await server.close()
        self._closed = True
        for queue in self._queues.values():
            if queue.task is not None:
                queue.task.cancel()
        tasks = [
            queue.task for queue in self._queues.values() if queue.task is not None
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for client in tuple(self._clients):
            client._close_from_broker()
        for queue in self._reply_queues.values():
            _signal_reply_queue_closed(queue)
        self._reply_queues.clear()
        self._servers.clear()
        self._clients.clear()

    async def _run_queue(self, queue: _Queue) -> None:
        while not self._closed:
            consumer = self._next_consumer(queue)
            if consumer is None or not queue.messages:
                queue.wake.clear()
                await queue.wake.wait()
                continue
            queued = queue.messages.popleft()
            if queued.publication.expires_at is not None and (
                queued.publication.expires_at <= utc_now()
            ):
                continue
            delivery = EncodedDelivery(
                message_id=queued.publication.message_id,
                routing_key=queued.publication.routing_key,
                body=queued.publication.body,
                headers=queued.publication.headers,
                received_at=utc_now(),
                attempt=queued.attempt,
                redelivered=queued.redelivered,
                correlation_id=queued.publication.correlation_id,
                reply_to=queued.publication.reply_to,
                native=queued.publication.native,
                expires_at=queued.publication.expires_at,
                subscription=consumer.server._subscriptions_by_queue.get(queue.name),
            )
            record = _DeliveryRecord(consumer.server, queue.name, delivery, queued)
            queue.deliveries[id(delivery)] = record
            consumer.in_flight += 1
            consumer.server._in_flight += 1
            consumer.server._delivery_queues[id(delivery)] = queue.name
            consumer.server._schedule_delivery(delivery)

    def _next_consumer(self, queue: _Queue) -> _Consumer | None:
        consumers = [
            consumer
            for consumer in queue.consumers.values()
            if (
                consumer.active
                and consumer.in_flight < consumer.prefetch
                and consumer.server._in_flight < consumer.server.prefetch
            )
        ]
        if not consumers:
            return None
        consumers.sort(key=lambda item: item.server.replica_id)
        consumer = consumers[queue.cursor % len(consumers)]
        queue.cursor = (queue.cursor + 1) % len(consumers)
        return consumer

    def _routes(self, routing_key: str, native: object | None) -> set[str]:
        if (
            isinstance(native, tuple)
            and len(native) == 2
            and all(isinstance(value, str) for value in native)
        ):
            return set(self._event_routes.get(native, set()))
        for service_label, queue_name in self._rpc_queues.items():
            if routing_key.startswith(f"{service_label}."):
                return {queue_name}
        return set()

    def _servers_by_replica(self, replica_id: str) -> InMemoryServerTransport | None:
        return next(
            (server for server in self._servers if server.replica_id == replica_id),
            None,
        )

    async def _remove_queue(self, queue_name: str) -> None:
        queue = self._queues.pop(queue_name, None)
        if queue is not None and queue.task is not None:
            queue.task.cancel()
            await asyncio.gather(queue.task, return_exceptions=True)
        for service_label, registered_queue in tuple(self._rpc_queues.items()):
            if registered_queue == queue_name:
                self._rpc_queues.pop(service_label, None)
        self._reliable_broadcast_owners.pop(queue_name, None)
        for server in self._servers:
            server._queue_names.discard(queue_name)
            server._subscriptions_by_queue.pop(queue_name, None)
        self._ephemeral_queues.discard(queue_name)
        for route, queues in tuple(self._event_routes.items()):
            queues.discard(queue_name)
            if not queues:
                self._event_routes.pop(route)

    def _wake_server_queues(self, server: InMemoryServerTransport) -> None:
        for queue_name in server._queue_names:
            queue = self._queues.get(queue_name)
            if queue is not None:
                queue.wake.set()

    def _require_open(self) -> None:
        if self._closed:
            raise TransportStateError("in-memory broker is closed")


class InMemoryServerTransport:
    """One competing-consumer server endpoint attached to an in-memory broker."""

    def __init__(
        self,
        broker: InMemoryBroker,
        service: ServiceIdentity,
        *,
        replica_id: str | None = None,
        prefetch: int = 1,
    ) -> None:
        if not isinstance(prefetch, int) or prefetch <= 0:
            raise ValueError("prefetch must be positive")
        self.broker = broker
        self.service = service
        self.replica_id = replica_id or str(uuid4())
        self.prefetch = prefetch
        self._status = TransportStatus.CREATED
        self._status_events: asyncio.Queue[TransportStatusEvent] = asyncio.Queue()
        self._queue_names: set[str] = set()
        self._subscriptions_by_queue: dict[str, EventSubscription] = {}
        self._delivery_queues: dict[int, str] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._in_flight = 0
        self._dispatcher: DeliveryDispatcher | None = None

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
        await self.broker.register_server(
            self, rpc_methods=rpc_methods, subscriptions=subscriptions
        )
        self._set_status(TransportStatus.PREPARED)

    async def start(self, dispatcher: DeliveryDispatcher) -> None:
        self._require(TransportStatus.PREPARED)
        self._dispatcher = dispatcher
        await self.broker.start_server(self)
        self._set_status(TransportStatus.RUNNING)

    async def settle(
        self, delivery: EncodedDelivery, outcome: SettlementRecommendation
    ) -> None:
        await self.broker.settle(self, delivery, outcome)

    async def publish_reply(self, publication: Publication) -> PublicationReceipt:
        self._require_open()
        return await self.broker.publish_reply(publication)

    async def stop_intake(self) -> None:
        if self._status in {TransportStatus.CLOSED, TransportStatus.QUIESCING}:
            return
        if self._status is not TransportStatus.RUNNING:
            raise TransportStateError("server intake has not started")
        self._set_status(TransportStatus.QUIESCING)
        await self.broker.stop_server(self, requeue=False)

    async def close(self) -> None:
        if self._status is TransportStatus.CLOSED:
            return
        if self._status is TransportStatus.RUNNING:
            await self.stop_intake()
        elif self._status is TransportStatus.PREPARED:
            await self.broker.stop_server(self)
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=1.0,
                )
            except TimeoutError:
                for task in tuple(self._tasks):
                    task.cancel()
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*self._tasks, return_exceptions=True),
                        timeout=0.1,
                    )
                except TimeoutError:
                    pass
        await self.broker.stop_server(self, requeue=True)
        self.broker._servers.discard(self)
        self._subscriptions_by_queue.clear()
        self._set_status(TransportStatus.CLOSED)

    async def statuses(self) -> AsyncIterator[TransportStatusEvent]:
        while True:
            event = await self._status_events.get()
            yield event
            if event.status is TransportStatus.CLOSED:
                return

    def unwrap(self) -> object:
        return self.broker

    def _schedule_delivery(self, delivery: EncodedDelivery) -> None:
        task = asyncio.create_task(self._dispatch(delivery))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _dispatch(self, delivery: EncodedDelivery) -> None:
        if self._dispatcher is None:
            return
        try:
            result = await self._dispatcher(delivery)
        except asyncio.CancelledError:
            raise
        except TransportError:
            if id(delivery) in self._delivery_queues:
                await self.settle(delivery, SettlementRecommendation.UNSETTLED)
            return
        except Exception:
            if id(delivery) in self._delivery_queues:
                try:
                    await self.settle(
                        delivery,
                        (
                            SettlementRecommendation.RETRY
                            if delivery.subscription is not None
                            else SettlementRecommendation.REJECT
                        ),
                    )
                except DuplicateSettlementError, TransportCapacityError:
                    pass
            return
        outcome = (
            result.recommendation
            if isinstance(result, InvocationCompletion)
            else result
        )
        if not isinstance(outcome, SettlementRecommendation):
            await self.settle(delivery, SettlementRecommendation.REJECT)
            return
        try:
            await self.settle(delivery, outcome)
        except DuplicateSettlementError, TransportCapacityError:
            pass

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
        if self._status not in {TransportStatus.PREPARED, TransportStatus.RUNNING}:
            raise TransportStateError("server transport is not available")


class InMemoryClientTransport:
    """Outbound endpoint with one bounded process-local reply route."""

    def __init__(
        self,
        broker: InMemoryBroker,
        *,
        reply_to: ReplyRoute | None = None,
        max_pending_replies: int = 10_000,
    ) -> None:
        if not isinstance(max_pending_replies, int) or max_pending_replies <= 0:
            raise ValueError("max_pending_replies must be positive")
        self.broker = broker
        self.reply_to = reply_to or ReplyRoute.generate()
        self.max_pending_replies = max_pending_replies
        self._reply_queue: asyncio.Queue[EncodedDelivery | None] | None = None
        self._status = TransportStatus.CREATED
        self._status_events: asyncio.Queue[TransportStatusEvent] = asyncio.Queue()
        self._pending_replies: set[UUID] = set()
        self._completed_replies: deque[UUID] = deque(maxlen=max_pending_replies)
        self._receive_replies = True

    @property
    def status(self) -> TransportStatus:
        return self._status

    @property
    def generation(self) -> int:
        return 0

    async def start(self, *, receive_replies: bool = True) -> None:
        if self._status is not TransportStatus.CREATED:
            raise TransportStateError("client transport has already started")
        if not isinstance(receive_replies, bool):
            raise TypeError("receive_replies must be boolean")
        self._receive_replies = receive_replies
        if receive_replies:
            self._reply_queue = await self.broker.register_reply_route(
                self.reply_to,
                self,
                max_pending_replies=self.max_pending_replies,
            )
        self._set_status(TransportStatus.RUNNING)

    async def publish_rpc(
        self, target: RpcTarget, publication: Publication
    ) -> PublicationReceipt:
        self._require_running()
        if not self._receive_replies:
            raise TransportStateError("reply reception is disabled")
        if publication.routing_key != target.routing_key:
            raise ValueError("publication routing key does not match RPC target")
        correlation_id = publication.correlation_id
        if correlation_id is None or publication.reply_to != self.reply_to:
            raise TransportCorrelationError(
                "RPC publications require this client's reply route and "
                "a correlation ID"
            )
        if correlation_id in self._pending_replies:
            raise TransportCorrelationError("RPC correlation is already pending")
        if correlation_id in self._completed_replies:
            raise TransportCorrelationError("RPC correlation was already completed")
        if len(self._pending_replies) >= self.max_pending_replies:
            raise TransportCapacityError("pending reply map is full")
        self._pending_replies.add(correlation_id)
        try:
            return await self.broker.publish(
                replace(publication, mandatory=True, native=None)
            )
        except Exception:
            self._pending_replies.discard(correlation_id)
            raise

    async def publish_event(
        self, identity: EventIdentity, publication: Publication
    ) -> PublicationReceipt:
        self._require_running()
        if publication.routing_key != identity.routing_key:
            raise ValueError("publication routing key does not match event identity")
        return await self.broker.publish(
            Publication(
                message_id=publication.message_id,
                routing_key=publication.routing_key,
                body=publication.body,
                headers=publication.headers,
                mandatory=publication.mandatory,
                correlation_id=publication.correlation_id,
                reply_to=publication.reply_to,
                native=(identity.exchange_name, identity.routing_key),
            )
        )

    def cancel_publication_after_reply(self, correlation_id: UUID) -> None:
        del correlation_id

    async def replies(self) -> AsyncIterator[EncodedDelivery]:
        self._require_running()
        if not self._receive_replies:
            raise TransportStateError("reply reception is disabled")
        assert self._reply_queue is not None
        while self._status is TransportStatus.RUNNING:
            reply = await self._reply_queue.get()
            if reply is None:
                return
            if reply.correlation_id is not None:
                if reply.correlation_id in self._completed_replies:
                    continue
                if reply.correlation_id not in self._pending_replies:
                    continue
                self._pending_replies.remove(reply.correlation_id)
                self._completed_replies.append(reply.correlation_id)
            yield reply

    async def close(self) -> None:
        if self._status is TransportStatus.CLOSED:
            return
        if self._receive_replies:
            await self.broker.unregister_reply_route(self.reply_to, self)
        self._set_status(TransportStatus.CLOSED)

    def cancel_pending(self, correlation_id: UUID) -> None:
        self._pending_replies.discard(correlation_id)

    def _close_from_broker(self) -> None:
        if self._status is not TransportStatus.CLOSED:
            self._set_status(TransportStatus.CLOSED)

    async def statuses(self) -> AsyncIterator[TransportStatusEvent]:
        while True:
            event = await self._status_events.get()
            yield event
            if event.status is TransportStatus.CLOSED:
                return

    def unwrap(self) -> object:
        return self.broker

    def _require_running(self) -> None:
        if self._status is not TransportStatus.RUNNING:
            raise TransportStateError("client transport is not running")

    def _set_status(self, status: TransportStatus) -> None:
        self._status = status
        self._status_events.put_nowait(TransportStatusEvent(status, utc_now()))


def _event_queue_name(subscription: EventSubscription) -> str:
    identity = subscription.identity
    prefix = (
        f"nestpy.event.{identity.source.label}.{identity.event}."
        f"v{identity.schema_version}"
    )
    if subscription.mode == "service_pool":
        assert subscription.destination is not None
        return (
            f"{prefix}--pool.{subscription.destination.label}."
            f"{subscription.subscription}"
        )
    if subscription.mode == "singleton":
        return f"{prefix}--singleton.{subscription.subscription}"
    assert subscription.instance_id is not None
    assert subscription.destination is not None
    return (
        f"{prefix}--broadcast.{subscription.destination.label}."
        f"{subscription.subscription}.{subscription.instance_id}"
    )


def _signal_reply_queue_closed(
    queue: asyncio.Queue[EncodedDelivery | None],
) -> None:
    while not queue.empty():
        queue.get_nowait()
    queue.put_nowait(None)


__all__ = [
    "InMemoryBroker",
    "InMemoryClientTransport",
    "InMemoryServerTransport",
]
