from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from nestpy_microservices import (
    EventIdentity,
    EventSubscription,
    Publication,
    RabbitMqClientTransport,
    RabbitMqConnectionManager,
    RabbitMqOptions,
    RabbitMqServerTransport,
    RpcProtocolError,
    ServiceCluster,
    ServiceIdentity,
    SettlementRecommendation,
    TransportIndeterminateError,
    TransportRejectedError,
)

SERVICE = ServiceIdentity("tests", "strict-protocol", 1)


class Message:
    def __init__(self, *, event: EventIdentity | None = None) -> None:
        self.message_id: object = str(uuid4())
        self.routing_key = (
            event.routing_key if event is not None else f"{SERVICE.label}.run"
        )
        self.body = b"payload"
        self.headers: object = {}
        self.redelivered = False
        self.correlation_id: object = None if event is not None else str(uuid4())
        self.reply_to: object = None if event is not None else "reply." + "a" * 32
        self.expiration = None
        self.actions: list[tuple[str, bool | None]] = []

    async def ack(self) -> None:
        self.actions.append(("ack", None))

    async def reject(self, *, requeue: bool) -> None:
        self.actions.append(("reject", requeue))

    async def nack(self, *, requeue: bool) -> None:
        self.actions.append(("nack", requeue))


class Queue:
    def __init__(self) -> None:
        self.callback = None

    async def consume(self, callback, **kwargs) -> None:
        del kwargs
        self.callback = callback

    async def cancel(self, tag: str) -> None:
        del tag


class Manager:
    options = RabbitMqOptions("amqp://localhost")
    generation = 0

    def __init__(self) -> None:
        self.queues: dict[str, Queue] = {}
        self.fenced: list[BaseException] = []
        self.channels = SimpleNamespace(
            consumer=SimpleNamespace(set_qos=_async_noop),
            reply=SimpleNamespace(set_qos=_async_noop),
        )

    def register_recovery_listener(self, listener) -> None:
        del listener

    def unregister_recovery_listener(self, listener) -> None:
        del listener

    async def declare(self, topology, *, role):
        del role
        for declaration in topology.queues:
            self.queues.setdefault(declaration.name, Queue())
        return self.queues

    async def notify_connection_lost(self, error) -> None:
        del error

    async def fence_connection(
        self, error: BaseException, *, generation: int | None = None
    ) -> None:
        del generation
        self.fenced.append(error)


@pytest.mark.asyncio
async def test_invalid_rpc_protocol_identifiers_are_rejected_before_dispatch() -> None:
    manager = Manager()
    server = RabbitMqServerTransport(cast(RabbitMqConnectionManager, manager), SERVICE)
    calls = 0

    async def dispatch(delivery):
        nonlocal calls
        calls += 1
        return SettlementRecommendation.ACK

    await server.prepare(rpc_methods=("run",))
    await server.start(dispatch)
    primary = manager.queues[f"nestpy.rpc.{SERVICE.label}"]
    assert primary.callback is not None

    mutations = (
        ("message_id", None),
        ("message_id", "not-a-uuid"),
        ("correlation_id", None),
        ("correlation_id", "not-a-uuid"),
        ("reply_to", None),
        ("reply_to", "invalid"),
    )
    for field_name, value in mutations:
        message = Message()
        setattr(message, field_name, value)
        await primary.callback(message)
        assert message.actions == [("reject", False)]

    assert calls == 0
    await server.close()


@pytest.mark.asyncio
async def test_invalid_event_identifiers_are_rejected_before_dispatch() -> None:
    manager = Manager()
    identity = EventIdentity(SERVICE, "changed", 1)
    subscription = EventSubscription(
        identity, "service_pool", "strict", destination=SERVICE
    )
    server = RabbitMqServerTransport(cast(RabbitMqConnectionManager, manager), SERVICE)
    calls = 0

    async def dispatch(delivery):
        nonlocal calls
        calls += 1
        return SettlementRecommendation.ACK

    await server.prepare(subscriptions=(subscription,))
    await server.start(dispatch)
    primary = next(
        queue
        for name, queue in manager.queues.items()
        if not name.endswith((".dead-letter", ".retry"))
    )
    assert primary.callback is not None

    for field_name, value in (
        ("message_id", None),
        ("correlation_id", "not-a-uuid"),
        ("reply_to", "reply." + "b" * 32),
        ("reply_to", "invalid"),
    ):
        message = Message(event=identity)
        setattr(message, field_name, value)
        await primary.callback(message)
        assert message.actions == [("reject", False)]

    assert calls == 0
    await server.close()


@pytest.mark.asyncio
async def test_untrusted_invalid_reply_identifiers_are_terminally_acked() -> None:
    manager = Manager()
    client = RabbitMqClientTransport(cast(RabbitMqConnectionManager, manager))

    for field_name, value in (
        ("message_id", None),
        ("message_id", "not-a-uuid"),
        ("correlation_id", None),
        ("correlation_id", "not-a-uuid"),
        ("reply_to", "reply." + "b" * 32),
        ("reply_to", "invalid"),
    ):
        message = Message()
        message.routing_key = client.reply_to.value
        message.reply_to = None
        setattr(message, field_name, value)
        await client._on_reply(message)
        assert message.actions == [("ack", None)]

    await client.close()


@pytest.mark.asyncio
async def test_event_only_client_never_opens_or_recovers_reply_routing() -> None:
    manager = Manager()
    client = RabbitMqClientTransport(cast(RabbitMqConnectionManager, manager))

    await client.start(receive_replies=False)
    assert manager.queues == {}

    await client.connection_lost(None)
    await client.connection_recovered()

    assert client.status.value == "running"
    assert client._recover_reply_route is False
    assert manager.queues == {}
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("message_id", "not-a-uuid"),
        ("headers", {"unsupported": object()}),
    ),
)
async def test_pending_malformed_reply_completes_with_protocol_failure(
    field_name: str,
    value: object,
) -> None:
    manager = Manager()
    client = RabbitMqClientTransport(cast(RabbitMqConnectionManager, manager))
    cluster = ServiceCluster(client)
    await cluster.start()
    published: list[Publication] = []
    publication_ready = asyncio.Event()

    class Publisher:
        async def publish(self, publication: Publication):
            published.append(publication)
            publication_ready.set()
            return SimpleNamespace()

    client._publisher = cast(Any, Publisher())
    caller = asyncio.create_task(
        cluster.service(SERVICE).request(
            "run",
            "request",
            response_type=str,
            timeout=1,
        )
    )
    await asyncio.wait_for(publication_ready.wait(), timeout=1)
    correlation_id = published[0].correlation_id
    assert correlation_id is not None
    message = Message()
    message.routing_key = client.reply_to.value
    message.correlation_id = str(correlation_id)
    message.reply_to = None
    setattr(message, field_name, value)
    reply_queue = manager.queues[client.reply_to.value]
    assert reply_queue.callback is not None

    await reply_queue.callback(message)

    with pytest.raises(RpcProtocolError, match="malformed RPC reply metadata"):
        await asyncio.wait_for(caller, timeout=1)
    await asyncio.sleep(0)
    assert message.actions == [("ack", None)]
    await cluster.close()
    await client.close()


@pytest.mark.asyncio
async def test_unknown_malformed_reply_is_acked_and_discarded() -> None:
    manager = Manager()
    client = RabbitMqClientTransport(cast(RabbitMqConnectionManager, manager))
    await client.start()
    message = Message()
    message.routing_key = client.reply_to.value
    message.reply_to = None
    message.message_id = "not-a-uuid"
    reply_queue = manager.queues[client.reply_to.value]
    assert reply_queue.callback is not None

    await reply_queue.callback(message)

    assert message.actions == [("ack", None)]
    assert client._reply_queue.empty()
    await client.close()


@pytest.mark.asyncio
async def test_generic_dispatcher_exception_and_retry_limit_reject_terminally() -> None:
    manager = Manager()
    server = RabbitMqServerTransport(
        cast(RabbitMqConnectionManager, manager),
        SERVICE,
        max_delivery_attempts=5,
    )

    async def broken(delivery):
        del delivery
        raise RuntimeError("programming failure")

    await server.prepare(rpc_methods=("run",))
    await server.start(broken)
    primary = manager.queues[f"nestpy.rpc.{SERVICE.label}"]
    assert primary.callback is not None
    failed = Message()
    await primary.callback(failed)
    assert failed.actions == [("reject", False)]

    async def retry(delivery):
        del delivery
        return SettlementRecommendation.RETRY

    server._dispatcher = retry
    bounded = Message()
    bounded.headers = {"x-delivery-count": 4, "x-death": [{"count": 4}]}
    await primary.callback(bounded)
    assert bounded.actions == [("reject", False)]
    await server.close()


@pytest.mark.asyncio
async def test_indeterminate_dispatch_leaves_rpc_unsettled_and_fences() -> None:
    manager = Manager()
    server = RabbitMqServerTransport(cast(RabbitMqConnectionManager, manager), SERVICE)

    async def uncertain(delivery):
        del delivery
        raise TransportIndeterminateError("reply confirm lost")

    await server.prepare(rpc_methods=("run",))
    await server.start(uncertain)
    primary = manager.queues[f"nestpy.rpc.{SERVICE.label}"]
    assert primary.callback is not None
    message = Message()

    await primary.callback(message)

    assert message.actions == []
    assert len(manager.fenced) == 1
    await server.close()


@pytest.mark.asyncio
async def test_definitive_retry_publish_rejection_is_terminal_without_fencing() -> None:
    manager = Manager()
    server = RabbitMqServerTransport(cast(RabbitMqConnectionManager, manager), SERVICE)

    class RejectedPublisher:
        async def publish(self, publication):
            del publication
            raise TransportRejectedError("retry queue is full")

    server._publisher = cast(Any, RejectedPublisher())

    async def retry(delivery):
        del delivery
        return SettlementRecommendation.RETRY

    await server.prepare(rpc_methods=("run",))
    await server.start(retry)
    primary = manager.queues[f"nestpy.rpc.{SERVICE.label}"]
    assert primary.callback is not None
    message = Message()

    await primary.callback(message)

    assert message.actions == [("reject", False)]
    assert manager.fenced == []
    await server.close()


@pytest.mark.asyncio
async def test_reply_queue_generation_replaces_loss_sentinel_before_recovery() -> None:
    manager = Manager()
    client = RabbitMqClientTransport(cast(RabbitMqConnectionManager, manager))
    await client.start()
    old_queue = client._reply_queue

    await client.connection_lost(ConnectionError("lost"))
    await client.connection_lost(ConnectionError("duplicate"))

    assert client._recover_reply_route is True
    assert old_queue.get_nowait() is None
    assert client._reply_queue is not old_queue
    assert client._reply_queue.empty()
    await client.close()


@pytest.mark.asyncio
async def test_server_close_fences_scheduled_callback_and_requeues_delivery() -> None:
    manager = Manager()
    server = RabbitMqServerTransport(cast(RabbitMqConnectionManager, manager), SERVICE)
    calls = 0

    async def dispatch(delivery):
        nonlocal calls
        del delivery
        calls += 1
        return SettlementRecommendation.ACK

    await server.prepare(rpc_methods=("run",))
    await server.start(dispatch)
    primary = manager.queues[f"nestpy.rpc.{SERVICE.label}"]
    callback = primary.callback
    assert callback is not None
    message = Message()
    broker_callbacks: list[asyncio.Task[None]] = []
    loop = asyncio.get_running_loop()

    def schedule_callback() -> None:
        broker_callbacks.append(asyncio.create_task(callback(message)))

    loop.call_soon(schedule_callback)

    await server.close()
    await asyncio.gather(*broker_callbacks)

    assert calls == 0
    assert message.actions == [("nack", True)]
    assert not server._callback_tasks


@pytest.mark.asyncio
async def test_client_close_fences_reply_callback_before_close_sentinel() -> None:
    manager = Manager()
    client = RabbitMqClientTransport(
        cast(RabbitMqConnectionManager, manager), max_pending_replies=1
    )
    await client.start()
    reply_queue = manager.queues[client.reply_to.value]
    callback = reply_queue.callback
    assert callback is not None

    admitted = Message()
    admitted.routing_key = client.reply_to.value
    admitted.reply_to = None
    admitted_correlation = UUID(cast(str, admitted.correlation_id))
    client._pending.add(admitted_correlation)
    await callback(admitted)
    assert client._reply_queue.full()

    racing = Message()
    racing.routing_key = client.reply_to.value
    racing.reply_to = None
    broker_callbacks: list[asyncio.Task[None]] = []
    loop = asyncio.get_running_loop()

    def schedule_callback() -> None:
        broker_callbacks.append(asyncio.create_task(callback(racing)))

    loop.call_soon(schedule_callback)

    await client.close()
    await asyncio.gather(*broker_callbacks)

    assert admitted.actions == [("ack", None)]
    assert racing.actions == [("ack", None)]
    assert client._reply_queue.get_nowait() is None
    assert client._reply_queue.empty()
    assert not client._callback_tasks


@pytest.mark.asyncio
async def test_server_skips_stale_generation_settlement() -> None:
    manager = Manager()
    server = RabbitMqServerTransport(cast(RabbitMqConnectionManager, manager), SERVICE)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def dispatch(delivery):
        del delivery
        entered.set()
        await release.wait()
        return SettlementRecommendation.ACK

    await server.prepare(rpc_methods=("run",))
    await server.start(dispatch)
    primary = manager.queues[f"nestpy.rpc.{SERVICE.label}"]
    assert primary.callback is not None

    async def immediate(delivery):
        del delivery
        return SettlementRecommendation.ACK

    server._dispatcher = immediate
    stale = Message()
    manager.generation = 1
    await server._on_message(
        stale,
        subscription=None,
        retry_exchange=None,
        generation=0,
    )
    assert stale.actions == []
    manager.generation = 0
    server._dispatcher = dispatch
    message = Message()
    callback = asyncio.create_task(primary.callback(message))
    await entered.wait()

    manager.generation = 1
    await server.connection_lost(ConnectionError("broker restarted"))
    release.set()
    await callback

    assert message.actions == []
    await server.close()


@pytest.mark.asyncio
async def test_client_does_not_ack_reply_from_lost_connection_generation() -> None:
    manager = Manager()
    client = RabbitMqClientTransport(cast(RabbitMqConnectionManager, manager))
    await client.start()
    correlation = uuid4()
    client._pending.add(correlation)
    message = Message()
    message.routing_key = client.reply_to.value
    message.correlation_id = str(correlation)

    await client._on_reply(message)
    delivery = client._reply_queue.get_nowait()
    assert delivery is not None
    manager.generation = 1
    await client._ack_reply(delivery)

    assert message.actions == []
    await client.close()


async def _async_noop(**kwargs: Any) -> None:
    del kwargs
