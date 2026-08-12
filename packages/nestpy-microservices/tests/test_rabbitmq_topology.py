from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from nestpy_microservices import (
    EventIdentity,
    EventSubscription,
    Publication,
    RabbitMqConnectionError,
    RpcTarget,
    ServiceIdentity,
    SettlementRecommendation,
    TransportIndeterminateError,
    TransportRejectedError,
    TransportTimeoutError,
    TransportUnroutableError,
)
from nestpy_microservices.rabbitmq import (
    QueueDeclaration,
    RabbitMqChannelRole,
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
from nestpy_microservices.rabbitmq.topology import retry_exchange_name

SERVICE = ServiceIdentity("kinker", "members", 1)


def test_options_redact_credentials_and_validate_defaults() -> None:
    options = RabbitMqOptions("amqps://user:secret@example.test/vhost", tls=True)

    assert "secret" not in repr(options)
    assert "example.test" in repr(options)
    assert "heartbeat=60" in options.connection_url
    assert "timeout=10.0" in options.connection_url
    assert "name=nestpy-microservices" in options.connection_url
    assert options.reconnect_interval == 5.0
    assert options.retry_delay_ms == 1_000
    assert options.max_delivery_attempts == 5
    with pytest.raises(ValueError):
        RabbitMqOptions("amqp://localhost", retry_delay_ms=0)
    with pytest.raises(ValueError):
        RabbitMqOptions("amqp://localhost", max_delivery_attempts=0)
    with pytest.raises(ValueError, match="tls must match"):
        RabbitMqOptions("amqp://localhost", tls=True)
    with pytest.raises(ValueError, match="controlled"):
        RabbitMqOptions("amqp://localhost/?heartbeat=0")
    with pytest.raises(ValueError, match="controlled"):
        RabbitMqOptions("amqps://localhost/?no_verify_ssl=1", tls=True)


def test_rpc_topology_uses_one_wildcard_service_queue() -> None:
    topology = compile_rpc_topology(SERVICE)

    assert topology.exchanges[0].name == "nestpy.rpc"
    assert topology.queues[0].name == "nestpy.rpc.kinker.members.v1"
    assert topology.bindings[0].routing_key == "kinker.members.v1.*"
    assert dict(topology.queues[0].arguments) == {
        "x-queue-type": "quorum",
        "x-delivery-limit": 5,
        "x-dead-letter-exchange": "nestpy.dead-letter",
        "x-dead-letter-routing-key": topology.queues[0].name,
    }
    assert topology.queues[1].name.endswith(".dead-letter")
    retry = topology.queues[2]
    assert retry.name.endswith(".retry")
    assert dict(retry.arguments) == {
        "x-queue-type": "classic",
        "x-message-ttl": 1_000,
        "x-dead-letter-exchange": "nestpy.rpc",
        "x-max-length": 10_000,
        "x-overflow": "reject-publish",
    }
    assert topology.bindings[2].routing_key == "kinker.members.v1.*"


def test_long_retry_exchange_name_is_stable_and_broker_safe() -> None:
    queue_name = "q" * 200

    first = retry_exchange_name(queue_name)
    second = retry_exchange_name(queue_name)

    assert first == second
    assert first.startswith("nestpy.retry.")
    assert len(first.encode("utf-8")) <= 127


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
    assert dict(event.queues[0].arguments)["x-delivery-limit"] == 5
    assert reply.queues[0].exclusive
    assert reply.queues[0].auto_delete
    assert dict(reply.queues[0].arguments) == {"x-expires": 300_000}

    ephemeral = compile_event_topology(
        EventSubscription(
            identity,
            "broadcast",
            "cache",
            destination=SERVICE,
            instance_id="replica-1",
        )
    )
    assert dict(ephemeral.queues[0].arguments) == {"x-queue-type": "classic"}

    custom_reply = compile_reply_topology(
        "reply." + "b" * 32,
        exchange="custom.rpc",
    )
    assert custom_reply.exchanges[0].name == "custom.rpc"
    assert custom_reply.bindings[0].exchange == "custom.rpc"


def test_reliable_broadcast_has_durable_nonexclusive_queue() -> None:
    identity = EventIdentity(SERVICE, "profile-created", 1)
    topology = compile_event_topology(
        EventSubscription(
            identity,
            "broadcast",
            "cache",
            destination=SERVICE,
            instance_id="replica-1",
            reliable=True,
        )
    )

    assert topology.queues[0].durable is True
    assert topology.queues[0].exclusive is False
    assert topology.queues[0].auto_delete is False
    assert dict(topology.queues[0].arguments) == {
        "x-queue-type": "classic",
        "x-expires": 604_800_000,
        "x-message-ttl": 86_400_000,
        "x-dead-letter-exchange": "nestpy.dead-letter",
        "x-dead-letter-routing-key": topology.queues[0].name,
    }


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


def test_connection_status_queue_is_bounded_and_coalesces_repeats() -> None:
    manager = RabbitMqConnectionManager(RabbitMqOptions("amqp://localhost"))

    for _ in range(100):
        manager._set_status(RabbitMqStatus.CONNECTING)
        manager._set_status(RabbitMqStatus.RECOVERING)

    assert manager._status_events.maxsize == 8
    assert manager._status_events.qsize() <= 8
    pending = []
    while not manager._status_events.empty():
        pending.append(manager._status_events.get_nowait())
    assert (
        pending
        == [
            RabbitMqStatus.CONNECTING,
            RabbitMqStatus.RECOVERING,
        ]
        * 4
    )


@pytest.mark.asyncio
async def test_connection_manager_owns_three_channels_without_eager_import(
    monkeypatch,
) -> None:
    calls: list[str] = []

    class Channel:
        async def declare_exchange(self, *args, **kwargs):
            calls.append(f"declare-exchange:{kwargs}")
            return Exchange()

        async def declare_queue(self, *args, **kwargs):
            calls.append(f"declare-queue:{kwargs}")
            return Queue()

        async def close(self):
            calls.append("channel-close")

    class Exchange:
        pass

    class Queue:
        async def bind(self, exchange, **kwargs):
            calls.append("bind")

    class Connection:
        close_callbacks = SimpleNamespace(
            add=lambda callback: calls.append("loss-hook")
        )
        reconnect_callbacks = SimpleNamespace(
            add=lambda callback: calls.append("recovery-hook")
        )

        async def channel(self, **kwargs):
            calls.append(f"channel:{kwargs}")
            return Channel()

        async def close(self):
            calls.append("connection-close")

    async def connect_robust(*args, **kwargs):
        calls.append(f"connect:{kwargs}")
        return Connection()

    fake_aio = SimpleNamespace(
        ExchangeType=SimpleNamespace(TOPIC="topic"),
        connect_robust=connect_robust,
    )
    monkeypatch.setattr(rabbitmq_connection, "require_aio_pika", lambda: fake_aio)
    manager = RabbitMqConnectionManager(RabbitMqOptions("amqps://localhost", tls=True))

    await manager.start()
    await manager.declare(
        compile_rpc_topology(SERVICE),
        role=RabbitMqChannelRole.CONSUMER,
    )

    class Listener:
        async def connection_lost(self, error):
            calls.append("listener-lost")

        async def connection_recovered(self):
            calls.append("listener-recovered")

    manager.register_recovery_listener(Listener())
    await manager.notify_connection_lost(ConnectionError("lost"))
    await manager.notify_connection_lost(ConnectionError("duplicate"))
    assert manager.status is RabbitMqStatus.RECOVERING
    await manager.notify_connection_recovered()
    assert manager.status is RabbitMqStatus.READY
    await manager.close()

    assert manager.status is RabbitMqStatus.CLOSED
    assert calls[0].startswith("connect:")
    assert "'ssl': True" in calls[0]
    assert "'on_return_raises': True" in calls[2]
    assert all(
        "'robust': False" in call for call in calls if call.startswith("declare-")
    )
    assert calls.count("bind") == 3
    assert calls.count("listener-lost") == 1
    assert "listener-recovered" in calls
    assert calls[-1] == "connection-close"


@pytest.mark.asyncio
async def test_connection_recovery_listener_is_bounded(monkeypatch) -> None:
    class Channel:
        async def close(self):
            return None

    class Connection:
        close_callbacks = SimpleNamespace(add=lambda callback: None)
        reconnect_callbacks = SimpleNamespace(add=lambda callback: None)

        async def channel(self, **kwargs):
            del kwargs
            return Channel()

        async def close(self):
            return None

    async def connect_robust(*args, **kwargs):
        del args, kwargs
        return Connection()

    fake_aio = SimpleNamespace(connect_robust=connect_robust)
    monkeypatch.setattr(rabbitmq_connection, "require_aio_pika", lambda: fake_aio)
    manager = RabbitMqConnectionManager(
        RabbitMqOptions("amqp://localhost", connection_timeout=0.01)
    )

    class HangingListener:
        async def connection_lost(self, error):
            del error
            await asyncio.Event().wait()

        async def connection_recovered(self):
            return None

    await manager.start()
    manager.register_recovery_listener(HangingListener())
    await manager.notify_connection_lost(ConnectionError("lost"))

    assert manager.status is RabbitMqStatus.RECOVERING
    assert isinstance(manager.recovery_error, TimeoutError)
    await manager.close()


@pytest.mark.asyncio
async def test_partial_channel_startup_cleans_up_in_reverse(monkeypatch) -> None:
    calls: list[str] = []

    class Channel:
        async def close(self) -> None:
            calls.append("consumer-close")

    class Connection:
        def __init__(self) -> None:
            self.calls = 0

        async def channel(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return Channel()
            raise ConnectionError("publisher channel failed")

        async def close(self) -> None:
            calls.append("connection-close")

    async def connect_robust(*args, **kwargs):
        return Connection()

    monkeypatch.setattr(
        rabbitmq_connection,
        "require_aio_pika",
        lambda: SimpleNamespace(connect_robust=connect_robust),
    )
    manager = RabbitMqConnectionManager(RabbitMqOptions("amqp://localhost"))

    with pytest.raises(RabbitMqConnectionError):
        await manager.start()

    assert calls == ["consumer-close", "connection-close"]
    assert manager.status is RabbitMqStatus.FAILED


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
            from aiormq import spec

            return spec.Basic.Ack()

    class Publisher:
        def __init__(self):
            self.default_exchange = Exchange()

        async def get_exchange(self, name: str, *, ensure: bool):
            return self.default_exchange

    fake_aio = SimpleNamespace(
        DeliveryMode=SimpleNamespace(
            PERSISTENT="persistent", NOT_PERSISTENT="transient"
        ),
        Message=Message,
    )
    monkeypatch.setattr(rabbitmq_publisher, "_load_aio_pika", lambda: fake_aio)
    manager = SimpleNamespace(
        options=RabbitMqOptions("amqp://localhost"),
        channels=RabbitMqChannels(
            consumer=object(),
            publisher=Publisher(),
            reply=object(),
        ),
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
    assert cast(Any, published[0][0]).kwargs["delivery_mode"] == "persistent"


@pytest.mark.asyncio
async def test_publisher_maps_unroutable_and_indeterminate_failures(
    monkeypatch,
) -> None:
    from aio_pika import exceptions
    from aiormq import spec

    returned = SimpleNamespace(
        delivery=spec.Basic.Return(reply_text="NO_ROUTE", routing_key="missing")
    )
    unroutable = exceptions.PublishError(cast(Any, returned), returned.delivery)
    uncertain = exceptions.ChannelInvalidStateError("closed")

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
        DeliveryMode=SimpleNamespace(
            PERSISTENT="persistent", NOT_PERSISTENT="transient"
        ),
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

    fenced: list[BaseException] = []

    async def fence_connection(
        error: BaseException, *, generation: int | None = None
    ) -> None:
        del generation
        fenced.append(error)

    unroutable_manager = SimpleNamespace(
        options=RabbitMqOptions("amqp://localhost"),
        channels=RabbitMqChannels(
            object(),
            Publisher(unroutable),
            object(),
        ),
    )
    with pytest.raises(TransportUnroutableError):
        await RabbitMqPublisher(
            cast(RabbitMqConnectionManager, unroutable_manager)
        ).publish(publication())

    uncertain_manager = SimpleNamespace(
        options=RabbitMqOptions("amqp://localhost"),
        channels=RabbitMqChannels(
            object(),
            Publisher(uncertain),
            object(),
        ),
        fence_connection=fence_connection,
    )
    with pytest.raises(TransportIndeterminateError):
        await RabbitMqPublisher(
            cast(RabbitMqConnectionManager, uncertain_manager)
        ).publish(publication())
    assert len(fenced) == 1


@pytest.mark.asyncio
async def test_publisher_maps_explicit_confirm_nack(monkeypatch) -> None:
    from aiormq import spec

    class Exchange:
        async def publish(self, *args, **kwargs):
            return spec.Basic.Nack()

    class Publisher:
        async def get_exchange(self, name: str, *, ensure: bool):
            return Exchange()

    fake_aio = SimpleNamespace(
        DeliveryMode=SimpleNamespace(PERSISTENT=2, NOT_PERSISTENT=1),
        Message=lambda **kwargs: kwargs,
    )
    monkeypatch.setattr(rabbitmq_publisher, "_load_aio_pika", lambda: fake_aio)
    manager = SimpleNamespace(
        options=RabbitMqOptions("amqp://localhost"),
        channels=RabbitMqChannels(object(), Publisher(), object()),
    )

    with pytest.raises(TransportRejectedError):
        await RabbitMqPublisher(cast(RabbitMqConnectionManager, manager)).publish(
            Publication(uuid4(), "route", b"body", {}, mandatory=True)
        )


@pytest.mark.asyncio
async def test_publisher_maps_real_delivery_error_nack(monkeypatch) -> None:
    from aio_pika import exceptions
    from aiormq import spec

    delivery_error = exceptions.DeliveryError(None, spec.Basic.Nack())

    class Exchange:
        async def publish(self, *args, **kwargs):
            raise delivery_error

    class Publisher:
        async def get_exchange(self, name: str, *, ensure: bool):
            return Exchange()

    fake_aio = SimpleNamespace(
        DeliveryMode=SimpleNamespace(PERSISTENT=2, NOT_PERSISTENT=1),
        Message=lambda **kwargs: kwargs,
    )
    monkeypatch.setattr(rabbitmq_publisher, "_load_aio_pika", lambda: fake_aio)
    manager = SimpleNamespace(
        options=RabbitMqOptions("amqp://localhost"),
        channels=RabbitMqChannels(object(), Publisher(), object()),
    )

    with pytest.raises(TransportRejectedError):
        await RabbitMqPublisher(cast(RabbitMqConnectionManager, manager)).publish(
            Publication(uuid4(), "route", b"body", {}, mandatory=True)
        )


@pytest.mark.asyncio
async def test_publisher_rejects_confirm_from_a_new_generation(monkeypatch) -> None:
    class Exchange:
        async def publish(self, *args, **kwargs):
            manager.generation = 1
            from aiormq import spec

            return spec.Basic.Ack()

    class Publisher:
        async def get_exchange(self, name: str, *, ensure: bool):
            return Exchange()

    fake_aio = SimpleNamespace(
        DeliveryMode=SimpleNamespace(PERSISTENT=2, NOT_PERSISTENT=1),
        Message=lambda **kwargs: kwargs,
    )
    monkeypatch.setattr(rabbitmq_publisher, "_load_aio_pika", lambda: fake_aio)
    fenced: list[tuple[BaseException, int | None]] = []

    async def fence_connection(error: BaseException, *, generation: int | None = None):
        fenced.append((error, generation))

    manager = SimpleNamespace(
        generation=0,
        options=RabbitMqOptions("amqp://localhost"),
        channels=RabbitMqChannels(object(), Publisher(), object()),
        fence_connection=fence_connection,
    )

    with pytest.raises(TransportIndeterminateError, match="generation"):
        await RabbitMqPublisher(cast(RabbitMqConnectionManager, manager)).publish(
            Publication(uuid4(), "route", b"body", {}, mandatory=True)
        )
    assert len(fenced) == 1
    assert fenced[0][1] == 0


@pytest.mark.asyncio
async def test_publisher_cancellation_during_confirm_fences_connection(
    monkeypatch,
) -> None:
    started = asyncio.Event()

    class Exchange:
        async def publish(self, *args, **kwargs):
            started.set()
            await asyncio.Event().wait()

    class Publisher:
        async def get_exchange(self, name: str, *, ensure: bool):
            return Exchange()

    fake_aio = SimpleNamespace(
        DeliveryMode=SimpleNamespace(PERSISTENT=2, NOT_PERSISTENT=1),
        Message=lambda **kwargs: kwargs,
    )
    monkeypatch.setattr(rabbitmq_publisher, "_load_aio_pika", lambda: fake_aio)
    fenced: list[BaseException] = []

    async def fence_connection(
        error: BaseException, *, generation: int | None = None
    ) -> None:
        del generation
        fenced.append(error)

    manager = SimpleNamespace(
        options=RabbitMqOptions("amqp://localhost"),
        channels=RabbitMqChannels(object(), Publisher(), object()),
        fence_connection=fence_connection,
    )
    task = asyncio.create_task(
        RabbitMqPublisher(cast(RabbitMqConnectionManager, manager)).publish(
            Publication(uuid4(), "route", b"body", {}, mandatory=True)
        )
    )

    await started.wait()
    task.cancel()
    with pytest.raises(TransportIndeterminateError):
        await task
    assert len(fenced) == 1
    assert isinstance(fenced[0], TransportIndeterminateError)


@pytest.mark.asyncio
async def test_publisher_cancellation_before_broker_write_is_timeout(
    monkeypatch,
) -> None:
    entered = asyncio.Event()

    class Publisher:
        async def get_exchange(self, name: str, *, ensure: bool):
            del name, ensure
            entered.set()
            await asyncio.Event().wait()

    fake_aio = SimpleNamespace(
        DeliveryMode=SimpleNamespace(PERSISTENT=2, NOT_PERSISTENT=1),
        Message=lambda **kwargs: kwargs,
    )
    monkeypatch.setattr(rabbitmq_publisher, "_load_aio_pika", lambda: fake_aio)
    manager = SimpleNamespace(
        options=RabbitMqOptions("amqp://localhost"),
        channels=RabbitMqChannels(object(), Publisher(), object()),
    )
    task = asyncio.create_task(
        RabbitMqPublisher(cast(RabbitMqConnectionManager, manager)).publish(
            Publication(uuid4(), "route", b"body", {}, mandatory=True)
        )
    )

    await entered.wait()
    task.cancel()
    with pytest.raises(TransportTimeoutError):
        await task


@pytest.mark.asyncio
async def test_server_consumes_and_manually_settles_incoming_messages() -> None:
    qos_calls: list[dict[str, object]] = []

    class Message:
        message_id = str(uuid4())
        routing_key = "kinker.members.v1.get"
        body = b"payload"
        headers = {"x-delivery-count": 1}
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
            self.consume_kwargs = None

        async def consume(self, callback, **kwargs):
            self.callback = callback
            self.consume_kwargs = kwargs

        async def cancel(self, tag: str) -> None:
            self.cancelled = True

    queue = Queue()

    async def set_qos(**kwargs):
        qos_calls.append(kwargs)

    consumer_channel = SimpleNamespace(set_qos=set_qos)

    class Manager:
        options = RabbitMqOptions("amqp://localhost")
        channels = SimpleNamespace(consumer=consumer_channel)

        def register_recovery_listener(self, listener):
            return None

        def unregister_recovery_listener(self, listener):
            return None

        async def declare(self, topology, *, role):
            assert role is RabbitMqChannelRole.CONSUMER
            return await _return_queue(queue, topology)

        async def notify_connection_lost(self, error):
            return None

    manager = Manager()
    server = RabbitMqServerTransport(cast(RabbitMqConnectionManager, manager), SERVICE)
    retried: list[Publication] = []

    class RetryPublisher:
        async def publish(self, publication: Publication):
            retried.append(publication)
            return SimpleNamespace()

    server._publisher = cast(Any, RetryPublisher())
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
    assert qos_calls == [{"prefetch_count": 1, "global_": False}]
    assert queue.consume_kwargs is not None
    assert queue.consume_kwargs["robust"] is False
    message = Message()
    assert queue.callback is not None
    await queue.callback(message)

    assert seen[0].attempt == 2
    assert seen[0].redelivered is True
    assert seen[0].native is not message
    assert not hasattr(seen[0].native, "ack")
    assert message.actions == [("ack", None)]
    retry_message = Message()
    await queue.callback(retry_message)
    reject_message = Message()
    await queue.callback(reject_message)
    assert retry_message.actions == [("ack", None)]
    assert retried[0].native == (
        "nestpy.rpc.kinker.members.v1.retry",
        "kinker.members.v1.get",
    )
    assert retried[0].headers["x-nestpy-retry-count"] == 2
    assert reject_message.actions == [("reject", False)]
    await server.close()
    assert queue.cancelled is True


@pytest.mark.asyncio
async def test_reliable_broadcast_uses_exact_subscription_and_delayed_retry() -> None:
    qos_calls: list[dict[str, object]] = []
    identity = EventIdentity(SERVICE, "profile-created", 1)
    subscription = EventSubscription(
        identity,
        "broadcast",
        "cache",
        destination=SERVICE,
        instance_id="replica-1",
        reliable=True,
    )

    class Message:
        message_id = str(uuid4())
        routing_key = identity.routing_key
        body = b"event"
        headers = {}
        redelivered = False
        correlation_id = None
        reply_to = None

        def __init__(self) -> None:
            self.actions = []

        async def ack(self) -> None:
            self.actions.append(("ack", None))

        async def nack(self, *, requeue: bool) -> None:
            self.actions.append(("nack", requeue))

        async def reject(self, *, requeue: bool) -> None:
            self.actions.append(("reject", requeue))

    class Queue:
        def __init__(self) -> None:
            self.callback = None
            self.consume_kwargs = None

        async def consume(self, callback, **kwargs):
            self.callback = callback
            self.consume_kwargs = kwargs

        async def cancel(self, tag: str) -> None:
            return None

    queues: dict[str, Queue] = {}

    async def set_qos(**kwargs):
        qos_calls.append(kwargs)

    class Manager:
        options = RabbitMqOptions("amqp://localhost")
        channels = SimpleNamespace(consumer=SimpleNamespace(set_qos=set_qos))

        def register_recovery_listener(self, listener):
            return None

        def unregister_recovery_listener(self, listener):
            return None

        async def declare(self, topology, *, role):
            for declaration in topology.queues:
                queues.setdefault(declaration.name, Queue())
            return queues

        async def notify_connection_lost(self, error):
            return None

    server = RabbitMqServerTransport(
        cast(RabbitMqConnectionManager, Manager()),
        SERVICE,
        prefetch=3,
    )
    retried: list[Publication] = []

    class RetryPublisher:
        async def publish(self, publication: Publication):
            retried.append(publication)
            return SimpleNamespace()

    server._publisher = cast(Any, RetryPublisher())
    seen = []

    async def dispatch(delivery):
        seen.append(delivery)
        return SettlementRecommendation.RETRY

    await server.prepare(subscriptions=(subscription,))
    await server.start(dispatch)
    assert qos_calls == [{"prefetch_count": 3, "global_": False}]
    primary = next(
        queue for name, queue in queues.items() if not name.endswith(".dead-letter")
    )
    assert primary.consume_kwargs is not None
    assert primary.consume_kwargs["exclusive"] is True
    assert primary.consume_kwargs["robust"] is False
    assert primary.callback is not None
    message = Message()
    await primary.callback(message)

    assert seen[0].subscription is subscription
    assert message.actions == [("ack", None)]
    assert retried[0].native == (
        next(name for name in queues if name.endswith(".retry")),
        identity.routing_key,
    )
    await server.close()


@pytest.mark.asyncio
async def test_stop_intake_attempts_every_consumer_cancellation() -> None:
    first = EventSubscription(
        EventIdentity(SERVICE, "first-event", 1),
        "service_pool",
        "first",
        destination=SERVICE,
    )
    second = EventSubscription(
        EventIdentity(SERVICE, "second-event", 1),
        "service_pool",
        "second",
        destination=SERVICE,
    )
    cancelled: list[str] = []
    qos_calls: list[dict[str, object]] = []

    async def set_qos(**kwargs):
        qos_calls.append(kwargs)

    class Queue:
        def __init__(self, name: str) -> None:
            self.name = name

        async def consume(self, callback, **kwargs):
            return None

        async def cancel(self, tag: str) -> None:
            cancelled.append(self.name)
            if len(cancelled) == 1:
                raise ConnectionError("first cancellation failed")

    queues: dict[str, Queue] = {}

    class Manager:
        options = RabbitMqOptions("amqp://localhost")
        channels = SimpleNamespace(consumer=SimpleNamespace(set_qos=set_qos))

        def register_recovery_listener(self, listener):
            return None

        def unregister_recovery_listener(self, listener):
            return None

        async def declare(self, topology, *, role):
            for declaration in topology.queues:
                queues.setdefault(declaration.name, Queue(declaration.name))
            return queues

    server = RabbitMqServerTransport(
        cast(RabbitMqConnectionManager, Manager()), SERVICE, prefetch=2
    )
    await server.prepare(subscriptions=(first, second))

    async def dispatch(delivery):
        return SettlementRecommendation.ACK

    await server.start(dispatch)
    assert qos_calls == [{"prefetch_count": 1, "global_": False}]

    with pytest.raises(RabbitMqConnectionError):
        await server.stop_intake()

    assert len(cancelled) == 2
    await server.close()


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
            from aiormq import spec

            return spec.Basic.Ack()

    class Queue:
        def __init__(self):
            self.callback = None
            self.cancelled = False
            self.consume_kwargs = None

        async def consume(self, callback, **kwargs):
            self.callback = callback
            self.consume_kwargs = kwargs

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
        DeliveryMode=SimpleNamespace(
            PERSISTENT="persistent", NOT_PERSISTENT="transient"
        ),
        Message=Message,
    )
    monkeypatch.setattr(rabbitmq_publisher, "_load_aio_pika", lambda: fake_aio)
    reply_qos: list[dict[str, object]] = []

    async def set_reply_qos(**kwargs):
        reply_qos.append(kwargs)

    reply_channel = SimpleNamespace(set_qos=set_reply_qos)
    declared_roles: list[RabbitMqChannelRole] = []

    class Manager:
        options = RabbitMqOptions("amqp://localhost")
        channels = SimpleNamespace(
            publisher=PublisherChannel(),
            reply=reply_channel,
        )

        def register_recovery_listener(self, listener):
            return None

        def unregister_recovery_listener(self, listener):
            return None

        async def declare(self, topology, *, role):
            declared_roles.append(role)
            return await _return_queue(queue, topology)

        async def notify_connection_lost(self, error):
            return None

    manager = Manager()
    client = RabbitMqClientTransport(
        cast(RabbitMqConnectionManager, manager), max_pending_replies=2
    )
    await client.start()
    assert queue.callback is not None
    assert queue.consume_kwargs is not None
    assert queue.consume_kwargs["robust"] is False
    assert reply_qos == [{"prefetch_count": 2, "global_": False}]
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
        def __init__(self, reply_correlation=correlation_id) -> None:
            self.message_id = str(uuid4())
            self.routing_key = client.reply_to.value
            self.body = b"reply"
            self.headers = {}
            self.redelivered = False
            self.correlation_id = str(reply_correlation)
            self.reply_to = None
            self.acked = False
            self.rejected = False

        async def ack(self):
            self.acked = True

        async def reject(self, *, requeue: bool):
            assert requeue is False
            self.rejected = True

    reply = Reply()
    await queue.callback(reply)
    replies = client.replies()
    received = await anext(replies)

    assert received.correlation_id == correlation_id
    assert reply.acked is False
    await cast(Any, replies).aclose()
    assert reply.acked is True
    assert published == [
        ("nestpy.rpc", rpc_publication.routing_key, True),
        (event.exchange_name, event.routing_key, True),
    ]
    assert declared_roles == [
        RabbitMqChannelRole.REPLY,
        RabbitMqChannelRole.PUBLISHER,
    ]

    malformed = Reply()
    malformed.headers = {"unsupported": object()}
    await queue.callback(malformed)
    assert malformed.acked is True
    assert malformed.rejected is False

    duplicate = Reply()
    unknown = Reply(uuid4())
    await queue.callback(duplicate)
    await queue.callback(unknown)
    old_reply_route = client.reply_to
    stream = client.replies()
    waiting = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    assert duplicate.acked is True
    assert unknown.acked is True
    await client.connection_lost(ConnectionError("lost"))
    with pytest.raises(StopAsyncIteration):
        await waiting
    await client.connection_recovered()
    assert client.reply_to != old_reply_route
    await client.close()
    assert queue.cancelled is True


async def _return_queue(queue, topology=None):
    if topology is not None and topology.queues:
        return {declaration.name: queue for declaration in topology.queues}
    return {"nestpy.rpc.kinker.members.v1": queue}


async def _async_noop(**kwargs) -> None:
    return None
