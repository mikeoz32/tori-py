"""Examples for consumer-owned event delivery modes."""

from __future__ import annotations

from typing import Annotated

from nestpy import DeferredModule, controller, module
from nestpy_microservices import (
    Context as MessageContextMarker,
)
from nestpy_microservices import (
    EventContext,
    EventDispatchMode,
    MicroservicesModule,
    MicroservicesOptions,
    Payload,
    ServerTransportFactory,
    ServiceIdentity,
    event_handler,
)

SOURCE = ServiceIdentity("examples", "catalog", 1)
RELIABLE_INSTANCE_OPTIONS = MicroservicesOptions(instance_id="cache-consumer-1")
RELIABLE_CONSUMER = ServiceIdentity("examples", "cache", 1)


@controller()
class EventModesController:
    """One class showing pool, singleton, and both broadcast policies."""

    @event_handler(
        SOURCE,
        "item-created",
        schema_version=1,
        mode=EventDispatchMode.SERVICE_POOL,
        subscription="catalog-workers",
    )
    async def pool(
        self,
        payload: Annotated[dict[str, object], Payload()],
    ) -> None:
        del payload

    @event_handler(
        SOURCE,
        "catalog-rebuilt",
        schema_version=1,
        mode=EventDispatchMode.SINGLETON,
        subscription="catalog-rebuild",
    )
    async def singleton(
        self,
        context: Annotated[EventContext, MessageContextMarker()],
    ) -> None:
        del context

    @event_handler(
        SOURCE,
        "cache-invalidated",
        schema_version=1,
        mode=EventDispatchMode.BROADCAST,
        subscription="ephemeral-cache",
        reliable=False,
    )
    async def ephemeral_broadcast(self) -> None:
        return None

    @event_handler(
        SOURCE,
        "cache-invalidated",
        schema_version=1,
        mode=EventDispatchMode.BROADCAST,
        subscription="reliable-cache",
        reliable=True,
    )
    async def reliable_broadcast(self) -> None:
        return None


@module(controllers=(EventModesController,))
class EventModesModule:
    """Module imported by the reliable-broadcast service root."""


def reliable_broadcast_root(transport: ServerTransportFactory) -> DeferredModule:
    """Configure a durable broadcast consumer with stable instance identity."""

    return MicroservicesModule.for_root(
        RELIABLE_CONSUMER,
        transport=transport,
        options=RELIABLE_INSTANCE_OPTIONS,
        imports=(EventModesModule,),
    )
