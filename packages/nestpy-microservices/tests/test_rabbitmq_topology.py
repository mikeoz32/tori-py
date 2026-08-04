from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from nestpy_microservices.rabbitmq import (
    QueueDeclaration,
    RabbitMqConnectionManager,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqStatus,
    RabbitMqTopology,
    RabbitMqTransport,
    compile_event_topology,
    compile_reply_topology,
    compile_rpc_topology,
    merge_topologies,
)
from nestpy_microservices.rabbitmq import connection as rabbitmq_connection

from nestpy_microservices import EventIdentity, EventSubscription, ServiceIdentity

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
