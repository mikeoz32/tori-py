from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("pytest_docker")

from nestpy_microservices.errors import RabbitMqConnectionError  # noqa: E402

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
    ServiceCluster,
    ServiceIdentity,
    SettlementRecommendation,
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
