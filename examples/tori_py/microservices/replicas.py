"""In-memory competing-replica example.

Replace the in-memory client/server transports with the RabbitMQ factories from
``RabbitMqModule`` for a broker-backed deployment.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from tori_py_microservices import (
    InMemoryBroker,
    InMemoryClientTransport,
    InMemoryServerTransport,
    MsgspecJsonMessageCodec,
    Publication,
    RpcResponseEnvelope,
    RpcTarget,
    ServiceCluster,
    ServiceIdentity,
    SettlementRecommendation,
    utc_now,
)

SERVICE = ServiceIdentity("examples", "workers", 1)
TARGET = RpcTarget(SERVICE, "process", 1)
AUDIT_SERVICE = ServiceIdentity("examples", "audit", 1)
AUDIT_TARGET = RpcTarget(AUDIT_SERVICE, "record", 1)


async def run_competing_replicas(
    payloads: Iterable[str],
    *,
    replica_count: int = 3,
) -> dict[str, int]:
    """Process payloads through one shared service queue and return replica use."""

    if replica_count <= 0:
        raise ValueError("replica_count must be positive")
    broker = InMemoryBroker()
    codec = MsgspecJsonMessageCodec()
    calls_by_replica = {f"replica-{index}": 0 for index in range(replica_count)}
    servers: list[InMemoryServerTransport] = []

    for replica_id in calls_by_replica:
        server = InMemoryServerTransport(broker, SERVICE, replica_id=replica_id)

        async def dispatch(delivery, *, replica_id=replica_id, server=server):
            request = codec.decode_request(delivery.body)
            calls_by_replica[replica_id] += 1
            response = RpcResponseEnvelope(
                message_id=request.message_id,
                correlation_id=request.correlation_id,
                completed_at=utc_now(),
                result=str(request.payload),
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

        await server.prepare(rpc_methods=(TARGET.method,))
        await server.start(dispatch)
        servers.append(server)

    client = InMemoryClientTransport(broker)
    cluster = ServiceCluster(client)
    try:
        await asyncio.gather(
            *(
                cluster.service(SERVICE).request(
                    TARGET.method,
                    payload,
                    response_type=str,
                )
                for payload in payloads
            )
        )
    finally:
        await cluster.close()
        for server in servers:
            await server.close()
        await broker.close()
    return calls_by_replica


async def call_multiple_services() -> dict[str, str]:
    """Call two logical services through one shared reply listener."""

    broker = InMemoryBroker()
    codec = MsgspecJsonMessageCodec()
    servers: list[InMemoryServerTransport] = []

    async def start(service: ServiceIdentity, target: RpcTarget) -> None:
        server = InMemoryServerTransport(broker, service)

        async def dispatch(delivery, *, server=server):
            request = codec.decode_request(delivery.body)
            response = RpcResponseEnvelope(
                message_id=request.message_id,
                correlation_id=request.correlation_id,
                completed_at=utc_now(),
                result=f"{service.name}:{request.payload}",
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

        await server.prepare(rpc_methods=(target.method,))
        await server.start(dispatch)
        servers.append(server)

    await start(SERVICE, TARGET)
    await start(AUDIT_SERVICE, AUDIT_TARGET)
    cluster = ServiceCluster(InMemoryClientTransport(broker))
    try:
        results = await asyncio.gather(
            cluster.service(SERVICE).request(
                TARGET.method, "item-1", response_type=str
            ),
            cluster.service(AUDIT_SERVICE).request(
                AUDIT_TARGET.method, "item-1", response_type=str
            ),
        )
        return {"workers": results[0], "audit": results[1]}
    finally:
        await cluster.close()
        for server in servers:
            await server.close()
        await broker.close()
