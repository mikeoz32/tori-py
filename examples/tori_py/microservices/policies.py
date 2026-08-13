"""Examples for application-owned RPC policies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from tori_py_microservices import (
    InMemoryBroker,
    InMemoryClientTransport,
    InMemoryServerTransport,
    RpcTimeoutError,
    ServiceCluster,
    ServiceIdentity,
)


async def demonstrate_offline_deadline() -> bool:
    """Show that an offline service produces a bounded client timeout."""

    broker = InMemoryBroker()
    server = InMemoryServerTransport(
        broker,
        ServiceIdentity("examples", "offline", 1),
    )
    await server.prepare(rpc_methods=("ping",))
    cluster = ServiceCluster(InMemoryClientTransport(broker))
    try:
        try:
            await cluster.service(ServiceIdentity("examples", "offline", 1)).request(
                "ping",
                None,
                response_type=str,
                timeout=0.01,
            )
        except RpcTimeoutError:
            return True
        return False
    finally:
        await cluster.close()
        await server.close()
        await broker.close()


@dataclass(frozen=True)
class OutboxRecord:
    """An application-owned record handed to a relay after its transaction."""

    event: str
    payload: object


async def relay_outbox_record(
    record: OutboxRecord,
    publish: Callable[[str, int, object], Awaitable[object]],
) -> None:
    """Keep outbox persistence/relay outside the transport package contract."""

    await publish(record.event, 1, record.payload)
