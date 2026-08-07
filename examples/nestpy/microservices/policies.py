"""Examples for application-owned RPC policies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated

from nestpy import controller

from nestpy_microservices import (
    Context,
    InMemoryBroker,
    InMemoryClientTransport,
    InMemoryServerTransport,
    Payload,
    RpcContext,
    RpcTimeoutError,
    ServiceCluster,
    ServiceIdentity,
    rpc,
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


@dataclass
class IdempotencyStore:
    """Application-owned deduplication state, not a built-in transport feature."""

    applied: set[str] = field(default_factory=set)

    def apply_once(self, key: str) -> str:
        if key in self.applied:
            return "duplicate"
        self.applied.add(key)
        return "applied"


@controller()
class MutatingController:
    """An explicit idempotency-key boundary for a mutating RPC."""

    def __init__(self, store: IdempotencyStore) -> None:
        self.store = store

    @rpc("update-profile")
    async def update(
        self,
        payload: Annotated[dict[str, object], Payload()],
        context: Annotated[RpcContext, Context()],
    ) -> str:
        del payload
        if context.idempotency_key is None:
            raise ValueError("mutating RPC requires an idempotency key")
        return self.store.apply_once(context.idempotency_key)


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
