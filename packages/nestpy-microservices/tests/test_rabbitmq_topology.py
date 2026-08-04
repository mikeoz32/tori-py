from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from nestpy_microservices.rabbitmq import (
    QueueDeclaration,
    RabbitMqClientTransport,
    RabbitMqConnectionManager,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqPublisher,
    RabbitMqServerTransport,
    RabbitMqStatus,
    RabbitMqTopology,
    RabbitMqTransport,
    compile_event_topology,
    compile_reply_topology,
    compile_rpc_topology,
    merge_topologies,
)
from nestpy_microservices.rabbitmq import connection as rabbitmq_connection
from nestpy_microservices.rabbitmq import publisher as rabbitmq_publisher
from nestpy_microservices.rabbitmq.connection import RabbitMqChannels

from nestpy_microservices import (
    EventIdentity,
    EventSubscription,
    Publication,
    RpcTarget,
    ServiceIdentity,
    SettlementRecommendation,
    TransportIndeterminateError,
    TransportUnroutableError,
)

SERVICE = ServiceIdentity("kinker", "members", 1)


def test_options_redact_credentials_and_validate_defaults() -> None:
    options = RabbitMqOptions("amqps://user:secret@example.test/vhost", tls=True)

    assert "secret" not in repr(options)
    assert "example.test" in repr(options)
    assert options.reconnect_interval == 5.0


def test_rpc_topology_uses_one_wildcard_service_queue() -> None:
    topology = compile_rpc_topology(SERVICE)

    assert topology.exchanges[0].name == "nestpy.rpc"
    assert topology.queues[0].name == "nestpy.rpc.kinker.members.v1"
    assert topology.bindings[0].routing_key == "kinker.members.v1.*"
    assert topology.queues[0].arguments == (("x-queue-type", "quorum"),)


def test_event_and_reply_topology_use_declared_queue_types() -> None:
    identity = EventIdentity(SERVICE, "profile-created", 1)
    subscription = EventSubscription(
        identity,
        "service_pool",
        "notify",
        destination=SERVICE,
    )
    event = compile_event_topology(subscription)
    reply = compile_reply_topology("reply." + "a" * 32)

    assert event.queues[0].name.endswith("--pool.kinker.members.v1.notify")
    assert event.queues[0].arguments == (("x-queue-type", "quorum"),)
    assert reply.queues[0].exclusive
    assert reply.queues[0].auto_delete


def test_topology_merge_rejects_conflicting_declarations() -> None:
    first = compile_rpc_topology(SERVICE)
    with pytest.raises(ValueError):
        merge_topologies(
            first,
            RabbitMqTopology(
                queues=(
                    QueueDeclaration(
                        first.queues[0].name,
                        durable=False,
                        exclusive=True,
                        auto_delete=True,
                    ),
                )
            ),
        )


def test_rabbitmq_root_is_deferred_and_base_import_is_lazy() -> None:
    descriptor = RabbitMqModule.for_root(RabbitMqOptions("amqp://localhost"))
    assert isinstance(descriptor.factory(), object)
    assert RabbitMqTransport().key == "default"
    assert "aio_pika" not in sys.modules
    manager = RabbitMqConnectionManager(RabbitMqOptions("amqp://localhost"))
    assert manager.status is RabbitMqStatus.CREATED


@pytest.mark.asyncio
async def test_connection_manager_owns_three_channels_without_eager_import(
    monkeypatch,
) -> None:
    calls: list[str] = []

    class Channel:
        async def declare_exchange(self, *args, **kwargs):
            return Exchange()

        async def declare_queue(self, *args, **kwargs):
            return Queue()

        async def close(self):
            calls.append("channel-close")

    class Exchange:
        async def bind(self, queue, **kwargs):
            calls.append("bind")

    class Queue:
        pass

    class Connection:
        async def channel(self, **kwargs):
            calls.append(f"channel:{kwargs['publisher_confirms']}")
            return Channel()

        async def close(self):
            calls.append("connection-close")

    async def connect_robust(*args, **kwargs):
        calls.append("connect")
        return Connection()

    fake_aio = SimpleNamespace(
        ExchangeType=SimpleNamespace(TOPIC="topic"),
        connect_robust=connect_robust,
    )
    monkeypatch.setattr(rabbitmq_connection, "require_aio_pika", lambda: fake_aio)
    manager = RabbitMqConnectionManager(RabbitMqOptions("amqp://localhost"))

    await manager.start()
    await manager.declare(compile_rpc_topology(SERVICE))
    await manager.close()

    assert manager.status is RabbitMqStatus.CLOSED
    assert calls[:4] == ["connect", "channel:False", "channel:True", "channel:False"]
    assert calls[-1] == "connection-close"


@pytest.mark.asyncio
async def test_publisher_uses_confirm_channel_and_maps_mandatory_returns(
    monkeypatch,
) -> None:
    published: list[tuple[object, str, bool]] = []

    class Message:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Exchange:
        async def publish(self, message, *, routing_key, mandatory):
            published.append((message, routing_key, mandatory))

    class Publisher:
        def __init__(self):
            self.default_exchange = Exchange()

        async def get_exchange(self, name: str, *, ensure: bool):
            return self.default_exchange

    fake_aio = SimpleNamespace(
        DeliveryMode=SimpleNamespace(PERSISTENT="persistent"),
        Message=Message,
    )
    monkeypatch.setattr(rabbitmq_publisher, "_load_aio_pika", lambda: fake_aio)
    manager = SimpleNamespace(
        channels=RabbitMqChannels(
            consumer=object(),
            publisher=Publisher(),
            reply=object(),
        )
    )
    publication = Publication(
        message_id=uuid4(),
        routing_key="kinker.members.v1.get",
        body=b"payload",
        headers={"content-type": "application/json"},
        mandatory=True,
    )

    receipt = await RabbitMqPublisher(cast(RabbitMqConnectionManager, manager)).publish(
        publication
    )

    assert receipt.message_id == publication.message_id
    assert receipt.routed is True
    assert published[0][1:] == (publication.routing_key, True)


@pytest.mark.asyncio
async def test_publisher_maps_unroutable_and_indeterminate_failures(
    monkeypatch,
) -> None:
    class DeliveryError(Exception):
        pass

    class ConnectionClosed(Exception):
        pass

    class Exchange:
        def __init__(self, error):
            self.error = error

        async def publish(self, *args, **kwargs):
            raise self.error

    class Publisher:
        def __init__(self, error):
            self.default_exchange = Exchange(error)

        async def get_exchange(self, name: str, *, ensure: bool):
            return self.default_exchange

    fake_aio = SimpleNamespace(
        DeliveryMode=SimpleNamespace(PERSISTENT="persistent"),
        Message=lambda **kwargs: kwargs,
    )
    monkeypatch.setattr(rabbitmq_publisher, "_load_aio_pika", lambda: fake_aio)

    def publication() -> Publication:
        return Publication(
            message_id=uuid4(),
            routing_key="kinker.members.v1.get",
            body=b"payload",
            headers={},
            mandatory=True,
        )

    unroutable_manager = SimpleNamespace(
        channels=RabbitMqChannels(
            object(),
            Publisher(DeliveryError()),
            object(),
        )
    )
    with pytest.raises(TransportUnroutableError):
        await RabbitMqPublisher(
            cast(RabbitMqConnectionManager, unroutable_manager)
        ).publish(publication())

    uncertain_manager = SimpleNamespace(
        channels=RabbitMqChannels(
            object(),
            Publisher(ConnectionClosed()),
            object(),
        )
    )
    with pytest.raises(TransportIndeterminateError):
        await RabbitMqPublisher(
            cast(RabbitMqConnectionManager, uncertain_manager)
        ).publish(publication())


@pytest.mark.asyncio
async def test_server_consumes_and_manually_settles_incoming_messages() -> None:
    class Message:
        message_id = str(uuid4())
        routing_key = "kinker.members.v1.get"
        body = b"payload"
        headers = {"x-attempt": 2}
        redelivered = True
        correlation_id = str(uuid4())
        reply_to = "reply." + "a" * 32

        def __init__(self) -> None:
            self.actions: list[tuple[str, bool | None]] = []

        async def ack(self) -> None:
            self.actions.append(("ack", None))

        async def nack(self, *, requeue: bool) -> None:
            self.actions.append(("nack", requeue))

        async def reject(self, *, requeue: bool) -> None:
            self.actions.append(("reject", requeue))

    class Queue:
        def __init__(self) -> None:
            self.callback = None
            self.cancelled = False

        async def consume(self, callback, **kwargs):
            self.callback = callback

        async def cancel(self, tag: str) -> None:
            self.cancelled = True

    queue = Queue()
    consumer_channel = SimpleNamespace(set_qos=_async_noop)
    manager = SimpleNamespace(
        declare=lambda topology: _return_queue(queue),
        channels=SimpleNamespace(consumer=consumer_channel),
    )
    server = RabbitMqServerTransport(cast(RabbitMqConnectionManager, manager), SERVICE)
    seen = []
    outcomes = iter(
        (
            SettlementRecommendation.ACK,
            SettlementRecommendation.RETRY,
            SettlementRecommendation.REJECT,
        )
    )

    async def dispatch(delivery):
        seen.append(delivery)
        return next(outcomes)

    await server.prepare(rpc_methods=("get",))
    await server.start(dispatch)
    message = Message()
    assert queue.callback is not None
    await queue.callback(message)

    assert seen[0].attempt == 2
    assert seen[0].redelivered is True
    assert message.actions == [("ack", None)]
    retry_message = Message()
    await queue.callback(retry_message)
    reject_message = Message()
    await queue.callback(reject_message)
    assert retry_message.actions == [("nack", True)]
    assert reject_message.actions == [("reject", False)]
    await server.close()
    assert queue.cancelled is True


@pytest.mark.asyncio
async def test_client_publishes_rpc_and_events_and_correlates_replies(
    monkeypatch,
) -> None:
    published: list[tuple[str, str, bool]] = []

    class Message:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Exchange:
        def __init__(self, name: str):
            self.name = name

        async def publish(self, message, *, routing_key, mandatory):
            published.append((self.name, routing_key, mandatory))

    class Queue:
        def __init__(self):
            self.callback = None
            self.cancelled = False

        async def consume(self, callback, **kwargs):
            self.callback = callback

        async def cancel(self, tag: str):
            self.cancelled = True

    queue = Queue()
    exchanges: dict[str, Exchange] = {}

    class PublisherChannel:
        default_exchange = Exchange("")

        async def get_exchange(self, name: str, *, ensure: bool):
            exchanges.setdefault(name, Exchange(name))
            return exchanges[name]

    fake_aio = SimpleNamespace(
        DeliveryMode=SimpleNamespace(PERSISTENT="persistent"),
        Message=Message,
    )
    monkeypatch.setattr(rabbitmq_publisher, "_load_aio_pika", lambda: fake_aio)
    manager = SimpleNamespace(
        declare=lambda topology: _return_queue(queue, topology),
        channels=SimpleNamespace(publisher=PublisherChannel()),
    )
    client = RabbitMqClientTransport(
        cast(RabbitMqConnectionManager, manager), max_pending_replies=2
    )
    await client.start()
    assert queue.callback is not None
    correlation_id = uuid4()
    rpc_publication = Publication(
        message_id=uuid4(),
        routing_key=SERVICE.label + ".get",
        body=b"request",
        headers={},
        correlation_id=correlation_id,
        reply_to=client.reply_to,
    )
    await client.publish_rpc(RpcTarget(SERVICE, "get", 1), rpc_publication)
    event = EventIdentity(SERVICE, "profile-created", 1)
    await client.publish_event(
        event,
        Publication(uuid4(), event.routing_key, b"event", {}, mandatory=True),
    )

    class Reply:
        def __init__(self) -> None:
            self.message_id = str(uuid4())
            self.routing_key = client.reply_to.value
            self.body = b"reply"
            self.headers = {}
            self.redelivered = False
            self.correlation_id = str(correlation_id)
            self.reply_to = None
            self.acked = False

        async def ack(self):
            self.acked = True

    reply = Reply()
    await queue.callback(reply)
    replies = client.replies()
    received = await anext(replies)

    assert received.correlation_id == correlation_id
    assert reply.acked is True
    assert published == [
        ("nestpy.rpc", rpc_publication.routing_key, True),
        (event.exchange_name, event.routing_key, True),
    ]
    await client.close()
    assert queue.cancelled is True


async def _return_queue(queue, topology=None):
    if topology is not None and topology.queues:
        return {declaration.name: queue for declaration in topology.queues}
    return {"nestpy.rpc.kinker.members.v1": queue}


async def _async_noop(**kwargs) -> None:
    return None
