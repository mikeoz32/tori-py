from __future__ import annotations

import asyncio
from collections.abc import Sequence
from uuid import uuid4

import pytest
from nestpy_microservices import (
    DuplicateSettlementError,
    EventIdentity,
    EventSubscription,
    InMemoryBroker,
    InMemoryClientTransport,
    InMemoryServerTransport,
    Publication,
    ReplyRoute,
    RpcTarget,
    ServiceIdentity,
    SettlementRecommendation,
    TransportStatus,
    TransportUnroutableError,
)

SERVICE = ServiceIdentity("kinker", "members", 1)
OTHER_SERVICE = ServiceIdentity("kinker", "groups", 1)
TARGET = RpcTarget(SERVICE, "ping", 1)


def publication(
    routing_key: str,
    *,
    reply_to: ReplyRoute | None = None,
) -> Publication:
    return Publication(
        message_id=uuid4(),
        routing_key=routing_key,
        body=b"{}",
        headers={},
        reply_to=reply_to,
    )


async def wait_for_count(values: Sequence[object], count: int) -> None:
    for _ in range(100):
        if len(values) >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected {count} values, got {len(values)}")


@pytest.mark.asyncio
async def test_rpc_competing_consumers_and_retry_redelivery() -> None:
    broker = InMemoryBroker()
    first = InMemoryServerTransport(broker, SERVICE, replica_id="a")
    second = InMemoryServerTransport(broker, SERVICE, replica_id="b")
    await first.prepare(rpc_methods=(TARGET.method,))
    await second.prepare(rpc_methods=(TARGET.method,))
    deliveries: list[tuple[str, int, bool]] = []
    attempts: dict[object, int] = {}

    async def dispatch(delivery):
        attempts[delivery.message_id] = attempts.get(delivery.message_id, 0) + 1
        deliveries.append(
            (delivery.routing_key, delivery.attempt, delivery.redelivered)
        )
        if attempts[delivery.message_id] == 1:
            return SettlementRecommendation.RETRY
        return SettlementRecommendation.ACK

    await first.start(dispatch)
    await second.start(dispatch)
    client = InMemoryClientTransport(broker)
    await client.start()
    for _ in range(2):
        await client.publish_rpc(
            TARGET,
            Publication(
                message_id=uuid4(),
                routing_key=TARGET.routing_key,
                body=b"{}",
                headers={},
                reply_to=client.reply_to,
                correlation_id=uuid4(),
            ),
        )
    await wait_for_count(deliveries, 3)

    assert {item[0] for item in deliveries} == {TARGET.routing_key}
    assert any(attempt == 2 and redelivered for _, attempt, redelivered in deliveries)
    assert first.status is TransportStatus.RUNNING
    assert second.status is TransportStatus.RUNNING
    await client.close()
    await first.close()
    await second.close()
    await broker.close()


@pytest.mark.asyncio
async def test_unroutable_mandatory_publication_is_rejected() -> None:
    broker = InMemoryBroker()
    client = InMemoryClientTransport(broker)
    await client.start()

    with pytest.raises(TransportUnroutableError):
        await client.publish_rpc(
            RpcTarget(OTHER_SERVICE, "missing", 1),
            Publication(
                message_id=uuid4(),
                routing_key="kinker.groups.v1.missing",
                body=b"{}",
                headers={},
                reply_to=client.reply_to,
                correlation_id=uuid4(),
            ),
        )

    await client.close()
    await broker.close()


@pytest.mark.asyncio
async def test_reply_route_is_separate_from_request_acceptance() -> None:
    broker = InMemoryBroker()
    server = InMemoryServerTransport(broker, SERVICE)
    await server.prepare(rpc_methods=(TARGET.method,))
    client = InMemoryClientTransport(broker)
    await client.start()
    correlation_id = uuid4()
    request = Publication(
        message_id=uuid4(),
        routing_key=TARGET.routing_key,
        body=b"{}",
        headers={},
        reply_to=client.reply_to,
        correlation_id=correlation_id,
    )
    await client.publish_rpc(TARGET, request)

    reply = Publication(
        message_id=uuid4(),
        routing_key=client.reply_to.value,
        body=b"{}",
        headers={},
        correlation_id=correlation_id,
    )
    await server.publish_reply(reply)
    received = await asyncio.wait_for(anext(client.replies()), timeout=1)

    assert received.routing_key == client.reply_to.value
    assert received.message_id == reply.message_id
    stream = client.replies()
    await server.publish_reply(reply)
    second_correlation = uuid4()
    second_request = Publication(
        message_id=uuid4(),
        routing_key=TARGET.routing_key,
        body=b"{}",
        headers={},
        reply_to=client.reply_to,
        correlation_id=second_correlation,
    )
    await client.publish_rpc(TARGET, second_request)
    second_reply = Publication(
        message_id=uuid4(),
        routing_key=client.reply_to.value,
        body=b"{}",
        headers={},
        correlation_id=second_correlation,
    )
    await server.publish_reply(second_reply)
    assert (await asyncio.wait_for(anext(stream), timeout=1)).correlation_id == (
        second_correlation
    )
    await client.close()
    await server.close()
    await broker.close()


@pytest.mark.asyncio
async def test_event_service_pool_competes_broadcast_fans_out() -> None:
    broker = InMemoryBroker()
    identity = EventIdentity(SERVICE, "profile-created", 1)
    service_subscription = EventSubscription(
        identity, "service_pool", "profiles", destination=SERVICE
    )
    singleton = EventSubscription(identity, "singleton", "global-audit")
    broadcast_a = EventSubscription(
        identity, "broadcast", "audit", destination=SERVICE, instance_id="a"
    )
    broadcast_b = EventSubscription(
        identity, "broadcast", "audit", destination=SERVICE, instance_id="b"
    )
    first = InMemoryServerTransport(broker, SERVICE, replica_id="a")
    second = InMemoryServerTransport(broker, SERVICE, replica_id="b")
    await first.prepare(subscriptions=(service_subscription, singleton, broadcast_a))
    await second.prepare(subscriptions=(service_subscription, singleton, broadcast_b))
    received: list[tuple[str, object, EventSubscription | None]] = []

    async def dispatch(delivery):
        received.append((delivery.routing_key, delivery.native, delivery.subscription))
        return SettlementRecommendation.ACK

    await first.start(dispatch)
    await second.start(dispatch)
    client = InMemoryClientTransport(broker)
    await client.start()
    await client.publish_event(identity, publication(identity.routing_key))
    await wait_for_count(received, 4)

    assert len(received) == 4
    assert {item.subscription for item in (service_subscription, singleton)} <= {
        delivery[2].subscription for delivery in received if delivery[2] is not None
    }
    await client.close()
    await first.close()
    await second.close()
    await broker.close()


@pytest.mark.asyncio
async def test_duplicate_settlement_is_rejected() -> None:
    broker = InMemoryBroker()
    server = InMemoryServerTransport(broker, SERVICE)
    await server.prepare(rpc_methods=(TARGET.method,))
    seen = []

    async def dispatch(delivery):
        seen.append(delivery)
        return SettlementRecommendation.ACK

    await server.start(dispatch)
    await broker.publish(publication(TARGET.routing_key))
    await wait_for_count(seen, 1)
    await asyncio.sleep(0.01)

    with pytest.raises(DuplicateSettlementError):
        await server.settle(seen[0], SettlementRecommendation.ACK)

    await server.close()
    await broker.close()


@pytest.mark.asyncio
async def test_client_close_signals_a_full_reply_queue_without_queue_full() -> None:
    broker = InMemoryBroker()
    client = InMemoryClientTransport(broker, max_pending_replies=1)
    await client.start()
    assert client._reply_queue is not None
    reply_queue = client._reply_queue
    await broker.publish_reply(
        Publication(
            uuid4(),
            client.reply_to.value,
            b"reply",
            {},
            correlation_id=uuid4(),
        )
    )
    assert reply_queue.full()

    await client.close()

    assert client.status is TransportStatus.CLOSED
    assert reply_queue.get_nowait() is None
    assert reply_queue.empty()
    await broker.close()


@pytest.mark.asyncio
async def test_broker_close_signals_a_full_reply_queue_and_closes_client() -> None:
    broker = InMemoryBroker()
    client = InMemoryClientTransport(broker, max_pending_replies=1)
    await client.start()
    assert client._reply_queue is not None
    reply_queue = client._reply_queue
    await broker.publish_reply(
        Publication(
            uuid4(),
            client.reply_to.value,
            b"reply",
            {},
            correlation_id=uuid4(),
        )
    )
    assert reply_queue.full()

    await broker.close()

    assert client.status is TransportStatus.CLOSED
    assert reply_queue.get_nowait() is None
    assert reply_queue.empty()
