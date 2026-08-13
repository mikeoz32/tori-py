"""Standalone RPC service and hybrid controller examples."""

from __future__ import annotations

from typing import Annotated

from tori_py import NestApplication, controller, get, module
from tori_py.starlette import StarletteAdapter
from tori_py_microservices import (
    Context,
    MicroservicesModule,
    Payload,
    RpcContext,
    ServerTransportFactory,
    ServiceIdentity,
    rpc,
)

HYBRID_SERVICE = ServiceIdentity("examples", "reports", 1)


@controller()
class CalculatorController:
    """A small controller with multiple public RPC methods."""

    @rpc("add")
    async def add(self, payload: Annotated[dict[str, int], Payload()]) -> int:
        return payload["left"] + payload["right"]

    @rpc("multiply")
    async def multiply(self, payload: Annotated[dict[str, int], Payload()]) -> int:
        return payload["left"] * payload["right"]


@module(controllers=(CalculatorController,))
class CalculatorModule:
    """Standalone service module discovered at application startup."""


@controller("/reports")
class HybridReportController:
    """One controller can expose HTTP and RPC behavior in one application."""

    @get("/health")
    async def health(self) -> dict[str, str]:
        return {"status": "ok"}

    @rpc("refresh")
    async def refresh(
        self,
        payload: Annotated[dict[str, str], Payload()],
        context: Annotated[RpcContext, Context()],
    ) -> dict[str, str | None]:
        return {"target": payload["target"], "request": context.request_id}


@module(controllers=(HybridReportController,))
class HybridApplicationModule:
    """HTTP plus RPC controller module."""


async def create_hybrid_application(
    transport: ServerTransportFactory,
) -> NestApplication:
    """Compose the HTTP adapter and one application-owned RPC service root."""

    @module(
        imports=(MicroservicesModule.for_root(HYBRID_SERVICE, transport=transport),),
        controllers=(HybridReportController,),
    )
    class HybridRoot:
        pass

    return await NestApplication.create(HybridRoot, adapter=StarletteAdapter())
