from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("pytest_docker")

from nestpy_microservices.errors import RabbitMqConnectionError  # noqa: E402
from nestpy_microservices.testing import assert_transport_conformance  # noqa: E402

from nestpy_microservices import (  # noqa: E402
    EventIdentity,
    EventSubscription,
    MsgspecJsonMessageCodec,
    Publication,
    RabbitMqClientTransport,
    RabbitMqConnectionManager,
    RabbitMqOptions,
    RabbitMqServerTransport,
    RpcResponseEnvelope,
    RpcTarget,
    ServiceCluster,
    ServiceIdentity,
    SettlementRecommendation,
    TransportUnroutableError,
    utc_now,
)

SERVICE = ServiceIdentity("integration", "worker", 1)
EVENT = EventIdentity(
    ServiceIdentity("integration", "publisher", 1),
    "profile-created",
    1,
)


@pytest.fixture(scope="session")
def docker_compose_file() -> str:
    return str(Path(__file__).with_name("docker-compose.yml"))


@pytest.fixture
def rabbitmq_url(docker_services, docker_ip: str) -> str:
    pytest.importorskip("aio_pika")
    port = docker_services.port_for("rabbitmq", 5672)
    docker_services.wait_until_responsive(
        check=lambda: _port_is_open(docker_ip, port),
        timeout=30,
        pause=0.5,
    )
    return f"amqp://nestpy:nestpy@{docker_ip}:{port}/"


def _port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_rpc_roundtrip_and_event_redelivery(rabbitmq_url: str) -> None:
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(rabbitmq_url, connection_name="pytest-integration")
    )
    server = RabbitMqServerTransport(manager, SERVICE, prefetch=4)
    client = RabbitMqClientTransport(manager, max_pending_replies=8)
    codec = MsgspecJsonMessageCodec()
    event_attempts = []

    async def dispatch(delivery):
        if delivery.routing_key == EVENT.routing_key:
            event_attempts.append(delivery)
            return (
                SettlementRecommendation.RETRY
                if len(event_attempts) == 1
                else SettlementRecommendation.ACK
            )
        request = codec.decode_request(delivery.body)
        response = RpcResponseEnvelope(
            message_id=uuid4(),
            correlation_id=request.correlation_id,
            completed_at=utc_now(),
            result=str(request.payload).upper(),
        )
        await server.publish_reply(
            Publication(
                message_id=response.message_id,
                routing_key=request.reply_to.value,
                body=codec.encode_response(response),
                headers={},
                mandatory=True,
                correlation_id=request.correlation_id,
            )
        )
        return SettlementRecommendation.ACK

    try:
        for attempt in range(10):
            try:
                await manager.start()
            except RabbitMqConnectionError:
                if attempt == 9:
                    raise
                await asyncio.sleep(0.5)
            else:
                break
        await server.prepare(
            rpc_methods=("ping",),
            subscriptions=(
                EventSubscription(
                    EVENT,
                    "service_pool",
                    "integration",
                    destination=SERVICE,
                ),
            ),
        )
        await server.start(dispatch)
        cluster = ServiceCluster(client, manage_transport=True)
        result = await cluster.service(SERVICE).request(
            "ping", "hello", response_type=str
        )
        assert result == "HELLO"

        await client.publish_event(
            EVENT,
            Publication(
                message_id=uuid4(),
                routing_key=EVENT.routing_key,
                body=b"event",
                headers={},
                mandatory=True,
            ),
        )

        async def wait_for_redelivery() -> None:
            while len(event_attempts) < 2:
                await asyncio.sleep(0.05)

        await asyncio.wait_for(wait_for_redelivery(), timeout=5)
        assert event_attempts[1].redelivered is True
        await cluster.close()
        await server.close()
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_mandatory_event_without_subscriber_is_unroutable(
    rabbitmq_url: str,
) -> None:
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(rabbitmq_url, connection_name="pytest-unroutable")
    )
    client = RabbitMqClientTransport(manager, max_pending_replies=2)
    identity = EventIdentity(EVENT.source, "orphaned-event", 1)
    try:
        await manager.start()
        await client.start()

        receipt = await client.publish_event(
            identity,
            Publication(
                uuid4(),
                identity.routing_key,
                b"event",
                {},
                mandatory=False,
            ),
        )
        assert receipt.routed is False

        with pytest.raises(TransportUnroutableError):
            await client.publish_event(
                identity,
                Publication(
                    uuid4(),
                    identity.routing_key,
                    b"event",
                    {},
                    mandatory=True,
                ),
            )
    finally:
        await client.close()
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_transport_conformance(rabbitmq_url: str) -> None:
    suffix = uuid4().hex[:8]
    service = ServiceIdentity("conformance", f"worker-{suffix}", 1)
    event = EventIdentity(
        ServiceIdentity("conformance", f"publisher-{suffix}", 1),
        "changed",
        1,
    )
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            rabbitmq_url,
            connection_name="pytest-conformance",
            retry_delay_ms=50,
            max_delivery_attempts=3,
        )
    )
    try:
        await manager.start()
        await assert_transport_conformance(
            RabbitMqServerTransport(
                manager,
                service,
                prefetch=2,
                retry_delay_ms=50,
                max_delivery_attempts=3,
            ),
            RabbitMqClientTransport(manager, max_pending_replies=8),
            service=service,
            event=event,
            max_delivery_attempts=3,
            max_inflight_deliveries=2,
            timeout=5,
        )
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.rabbitmq
async def test_rabbitmq_server_close_drains_admitted_callback(
    rabbitmq_url: str,
) -> None:
    service = ServiceIdentity("lifecycle", f"worker-{uuid4().hex[:8]}", 1)
    target = RpcTarget(service, "wait", 1)
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(rabbitmq_url, connection_name="pytest-close-drain")
    )
    server = RabbitMqServerTransport(manager, service)
    client = RabbitMqClientTransport(manager, max_pending_replies=1)
    admitted = asyncio.Event()
    release = asyncio.Event()

    async def dispatch(delivery):
        del delivery
        admitted.set()
        await release.wait()
        return SettlementRecommendation.ACK

    try:
        await manager.start()
        await server.prepare(rpc_methods=(target.method,))
        await server.start(dispatch)
        await client.start()
        await client.publish_rpc(
            target,
            Publication(
                uuid4(),
                target.routing_key,
                b"request",
                {},
                correlation_id=uuid4(),
                reply_to=client.reply_to,
            ),
        )
        await asyncio.wait_for(admitted.wait(), timeout=5)

        closing = asyncio.create_task(server.close())
        await asyncio.sleep(0.05)
        assert not closing.done()
        release.set()
        await asyncio.wait_for(closing, timeout=5)

        assert not server._callback_tasks
        await client.close()
    finally:
        release.set()
        await server.close()
        await client.close()
        await manager.close()
