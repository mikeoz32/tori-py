from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from nestpy_microservices import (
    InMemoryBroker,
    InMemoryClientTransport,
    InMemoryServerTransport,
    MsgspecJsonMessageCodec,
    Publication,
    RpcResponseEnvelope,
    RpcTarget,
    RpcTimeoutError,
    ServiceCluster,
    ServiceClusterOptions,
    ServiceIdentity,
    SettlementRecommendation,
    TransportCapacityError,
    utc_now,
)

SERVICE = ServiceIdentity("kinker", "members", 1)
TARGET = RpcTarget(SERVICE, "ping", 1)


@pytest.mark.asyncio
async def test_cluster_uses_one_reply_route_for_rpc_success() -> None:
    broker = InMemoryBroker()
    server = InMemoryServerTransport(broker, SERVICE)
    await server.prepare(rpc_methods=(TARGET.method,))
    codec = MsgspecJsonMessageCodec()

    async def dispatch(delivery):
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

    await server.start(dispatch)
    client = InMemoryClientTransport(broker)
    cluster = ServiceCluster(client)

    result = await cluster.service(SERVICE).request("ping", "hello", response_type=str)

    assert result == "HELLO"
    await cluster.close()
    await server.close()
    await broker.close()


@pytest.mark.asyncio
async def test_cluster_timeout_removes_pending_call() -> None:
    broker = InMemoryBroker()
    server = InMemoryServerTransport(broker, SERVICE)
    await server.prepare(rpc_methods=(TARGET.method,))

    async def dispatch(delivery):
        del delivery
        return SettlementRecommendation.ACK

    await server.start(dispatch)
    cluster = ServiceCluster(
        InMemoryClientTransport(broker),
        options=ServiceClusterOptions(default_rpc_timeout=0.01, max_rpc_timeout=1),
    )

    with pytest.raises(RpcTimeoutError):
        await cluster.service(SERVICE).request("ping", "hello", response_type=str)

    assert not cluster._pending
    await cluster.close()
    await server.close()
    await broker.close()


@pytest.mark.asyncio
async def test_cluster_rejects_pending_map_exhaustion_before_publish() -> None:
    broker = InMemoryBroker()
    client = InMemoryClientTransport(broker)
    cluster = ServiceCluster(
        client,
        options=ServiceClusterOptions(max_pending_requests=1),
    )
    await cluster.start()
    loop = asyncio.get_running_loop()
    pending = loop.create_future()
    cluster._pending[uuid4()] = pending

    with pytest.raises(TransportCapacityError):
        await cluster.service(SERVICE).request("ping", "hello", response_type=str)

    await cluster.close()
    assert isinstance(pending.exception(), Exception)
    await broker.close()
