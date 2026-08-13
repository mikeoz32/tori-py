from __future__ import annotations

import asyncio
from uuid import uuid4

from tori_py_microservices import (
    ClientTransport,
    EventIdentity,
    EventSubscription,
    Publication,
    RpcTarget,
    ServerTransport,
    ServiceIdentity,
    SettlementRecommendation,
    TransportStatus,
    TransportUnroutableError,
)


async def assert_transport_conformance(
    server: ServerTransport,
    client: ClientTransport,
    *,
    service: ServiceIdentity,
    event: EventIdentity,
    max_delivery_attempts: int,
    max_inflight_deliveries: int,
    timeout: float,
) -> None:
    """Exercise shared at-least-once routing, bounds, and lifecycle semantics."""

    if max_inflight_deliveries < 2:
        raise ValueError("conformance requires one slot for RPC and event consumers")

    subscription = EventSubscription(
        event,
        "service_pool",
        "conformance",
        destination=service,
    )
    rpc_seen = []
    retry_seen = []
    terminal_seen = []
    unsettled_seen = []
    reply_observed = asyncio.Event()
    response_preceded_settlement = False
    capacity_active = 0
    capacity_peak = 0
    capacity_completed = 0
    capacity_saturated = asyncio.Event()
    capacity_release = asyncio.Event()
    drain_started = asyncio.Event()
    drain_release = asyncio.Event()
    drain_completed = asyncio.Event()

    async def dispatch(delivery):
        nonlocal capacity_active, capacity_completed, capacity_peak
        nonlocal response_preceded_settlement
        if delivery.subscription is not None:
            if delivery.body == b"retry":
                retry_seen.append(delivery)
                return SettlementRecommendation.RETRY
            if delivery.body == b"terminal":
                terminal_seen.append(delivery)
                return SettlementRecommendation.REJECT
            if delivery.body == b"unsettled":
                unsettled_seen.append(delivery)
                return (
                    SettlementRecommendation.UNSETTLED
                    if delivery.attempt == 1
                    else SettlementRecommendation.ACK
                )
            if delivery.body.startswith(b"capacity"):
                capacity_active += 1
                capacity_peak = max(capacity_peak, capacity_active)
                if capacity_active == 1:
                    capacity_saturated.set()
                try:
                    await capacity_release.wait()
                finally:
                    capacity_active -= 1
                    capacity_completed += 1
                return SettlementRecommendation.ACK
            if delivery.body == b"drain":
                drain_started.set()
                await drain_release.wait()
                drain_completed.set()
                return SettlementRecommendation.ACK
            raise AssertionError(f"unexpected conformance body {delivery.body!r}")
        rpc_seen.append(delivery)
        assert delivery.correlation_id is not None
        assert delivery.reply_to is not None
        reply = Publication(
            uuid4(),
            delivery.reply_to.value,
            b"response",
            {},
            mandatory=True,
            correlation_id=delivery.correlation_id,
        )
        await server.publish_reply(reply)
        await server.publish_reply(reply)
        await server.publish_reply(
            Publication(
                uuid4(),
                delivery.reply_to.value,
                b"unknown",
                {},
                mandatory=True,
                correlation_id=uuid4(),
            )
        )
        await asyncio.wait_for(reply_observed.wait(), timeout=timeout)
        response_preceded_settlement = True
        return SettlementRecommendation.ACK

    await server.prepare(
        rpc_methods=("conformance",),
        subscriptions=(subscription,),
    )
    await server.start(dispatch)
    await client.start()
    assert server.unwrap() is not None
    assert client.unwrap() is not None
    replies = client.replies()

    async def receive_reply():
        reply = await anext(replies)
        reply_observed.set()
        return reply

    reply_task = asyncio.create_task(receive_reply())
    correlation_id = uuid4()
    rpc_route = f"{service.label}.conformance"
    await client.publish_rpc(
        RpcTarget(service, "conformance", 1),
        Publication(
            uuid4(),
            rpc_route,
            b"request",
            {},
            mandatory=True,
            correlation_id=correlation_id,
            reply_to=client.reply_to,
        ),
    )
    reply = await asyncio.wait_for(reply_task, timeout=timeout)
    assert reply.correlation_id == correlation_id

    await _wait_for(lambda: bool(rpc_seen), timeout)
    assert rpc_seen[0].routing_key == rpc_route
    await _wait_for(lambda: response_preceded_settlement, timeout)
    assert response_preceded_settlement

    async def receive_filtered_reply():
        return await anext(replies)

    filtered_reply = asyncio.create_task(receive_filtered_reply())
    await asyncio.sleep(min(timeout / 10, 0.05))
    assert not filtered_reply.done()

    missing_service = ServiceIdentity(
        "conformance",
        f"missing-{uuid4().hex[:8]}",
        1,
    )
    missing_target = RpcTarget(missing_service, "missing", 1)
    missing_correlation = uuid4()
    try:
        await client.publish_rpc(
            missing_target,
            Publication(
                uuid4(),
                missing_target.routing_key,
                b"missing",
                {},
                mandatory=True,
                correlation_id=missing_correlation,
                reply_to=client.reply_to,
            ),
        )
    except TransportUnroutableError:
        pass
    else:  # pragma: no cover - both reference transports must reject this
        raise AssertionError("mandatory unknown RPC route was accepted")

    await client.publish_event(
        event,
        Publication(uuid4(), event.routing_key, b"retry", {}, mandatory=True),
    )
    await _wait_for(
        lambda: len(retry_seen) >= max_delivery_attempts,
        timeout,
    )
    assert [delivery.attempt for delivery in retry_seen] == list(
        range(1, max_delivery_attempts + 1)
    )
    await asyncio.sleep(min(timeout / 10, 0.1))
    assert len(retry_seen) == max_delivery_attempts
    assert retry_seen[-1].redelivered is True
    assert all(delivery.subscription == subscription for delivery in retry_seen)
    assert all(delivery.routing_key == event.routing_key for delivery in retry_seen)

    await client.publish_event(
        event,
        Publication(uuid4(), event.routing_key, b"terminal", {}, mandatory=True),
    )
    await _wait_for(lambda: len(terminal_seen) == 1, timeout)
    await asyncio.sleep(min(timeout / 10, 0.1))
    assert len(terminal_seen) == 1

    capacity_count = max_inflight_deliveries + 1
    for index in range(capacity_count):
        await client.publish_event(
            event,
            Publication(
                uuid4(),
                event.routing_key,
                f"capacity-{index}".encode(),
                {},
                mandatory=True,
            ),
        )
    await asyncio.wait_for(capacity_saturated.wait(), timeout=timeout)
    await asyncio.sleep(min(timeout / 10, 0.1))
    assert 1 <= capacity_peak <= max_inflight_deliveries
    capacity_release.set()
    await _wait_for(lambda: capacity_completed == capacity_count, timeout)

    await client.publish_event(
        event,
        Publication(uuid4(), event.routing_key, b"unsettled", {}, mandatory=True),
    )
    await _wait_for(lambda: len(unsettled_seen) == 2, timeout)
    assert [delivery.attempt for delivery in unsettled_seen] == [1, 2]
    assert unsettled_seen[1].redelivered is True
    await _wait_for(lambda: client.status is TransportStatus.RUNNING, timeout)
    if not filtered_reply.done():
        filtered_reply.cancel()
    await asyncio.gather(filtered_reply, return_exceptions=True)

    await client.publish_event(
        event,
        Publication(uuid4(), event.routing_key, b"drain", {}, mandatory=True),
    )
    await asyncio.wait_for(drain_started.wait(), timeout=timeout)

    stopping = asyncio.create_task(server.stop_intake())
    await asyncio.sleep(min(timeout / 10, 0.05))
    assert server.status is TransportStatus.QUIESCING
    assert not drain_completed.is_set()
    drain_release.set()
    await asyncio.wait_for(stopping, timeout=timeout)
    await server.stop_intake()
    await asyncio.wait_for(drain_completed.wait(), timeout=timeout)
    await client.close()
    await client.close()
    await server.close()
    await server.close()
    assert client.status is TransportStatus.CLOSED
    assert server.status is TransportStatus.CLOSED


async def _wait_for(predicate, timeout: float) -> None:
    async def wait() -> None:
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout=timeout)


__all__ = ["assert_transport_conformance"]
