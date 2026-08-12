"""HTTP gateway that talks to services only through RabbitMQ RPC."""

from __future__ import annotations

import asyncio
from typing import Annotated

from nestpy import (
    Body,
    NestApplication,
    Path,
    PipelineResult,
    ValueProvider,
    controller,
    get,
    module,
    post,
    status,
)
from nestpy.http import HttpException, MsgspecValidationPipe
from nestpy.starlette import RequestContext, StarletteAdapter
from nestpy.starlette.errors import problem_response
from nestpy_microservices import (
    ClientsModule,
    RabbitMqConnectionError,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    RemoteRpcError,
    RpcOutcomeUnknownError,
    RpcProtocolError,
    RpcTimeoutError,
    TransportError,
    TransportIndeterminateError,
    TransportTimeoutError,
    UnknownServiceError,
)

from examples.nestpy.microservices_app.common.contracts import (
    CatalogItem,
    CreateCatalogItem,
    CreateOrder,
    Notification,
    Order,
)
from examples.nestpy.microservices_app.common.infrastructure import rabbitmq_url
from examples.nestpy.microservices_app.common.services import (
    CatalogService,
    NotificationsService,
    OrdersService,
)


@controller()
class GatewayController:
    def __init__(
        self,
        catalog: CatalogService,
        orders: OrdersService,
        notifications: NotificationsService,
    ) -> None:
        self._catalog = catalog
        self._orders = orders
        self._notifications = notifications

    @get("/health")
    async def health(self) -> dict[str, str]:
        return {"status": "ok"}

    @get("/ready")
    async def ready(self) -> dict[str, str]:
        try:
            await asyncio.gather(
                self._catalog.health(),
                self._orders.health(),
                self._notifications.health(),
            )
        except Exception as error:
            raise HttpException(503, "Gateway dependencies are not ready.") from error
        return {"status": "ready"}

    @post("/catalog/items")
    @status(201)
    async def create_item(
        self,
        body: Annotated[CreateCatalogItem, Body()],
    ) -> CatalogItem:
        return await self._catalog.create_item(body.name, body.price_cents)

    @get("/catalog/items/{item_id}")
    async def get_item(
        self,
        item_id: Annotated[int, Path("item_id")],
    ) -> CatalogItem:
        return await self._catalog.get_item(item_id)

    @post("/orders")
    @status(201)
    async def create_order(
        self,
        body: Annotated[CreateOrder, Body()],
    ) -> Order:
        return await self._orders.create_order(body.item_id, body.quantity)

    @get("/orders/{order_id}")
    async def get_order(
        self,
        order_id: Annotated[int, Path("order_id")],
    ) -> Order:
        return await self._orders.get_order(order_id)

    @get("/notifications")
    async def list_notifications(self) -> list[Notification]:
        return await self._notifications.list_notifications()


class GatewayErrorFilter:
    """Translate stable RPC and HTTP failures at the gateway boundary."""

    async def catch(
        self,
        error: Exception,
        context: RequestContext,
    ) -> PipelineResult:
        match error:
            case HttpException():
                status_code = error.status_code
                detail = error.detail
                title = error.title
            case RemoteRpcError():
                status_code = {
                    "invalid_request": 400,
                    "not_found": 404,
                    "conflict": 409,
                }.get(error.code, 502)
                detail = error.message
                title = None
            case UnknownServiceError():
                status_code = 503
                detail = "A required service is unavailable."
                title = None
            case RpcTimeoutError():
                status_code = 504
                detail = "A service request timed out."
                title = None
            case RpcOutcomeUnknownError():
                status_code = 502
                detail = "A service request outcome is unknown."
                title = None
            case TransportIndeterminateError():
                status_code = 502
                detail = "A service request outcome is unknown."
                title = None
            case TransportTimeoutError():
                status_code = 504
                detail = "A service transport operation timed out."
                title = None
            case RabbitMqConnectionError() | TransportError():
                status_code = 503
                detail = "The service transport is unavailable."
                title = None
            case RpcProtocolError():
                status_code = 502
                detail = "A service returned an invalid response."
                title = None
            case _:
                status_code = 500
                detail = "The gateway could not complete the request."
                title = None
        return PipelineResult.from_response(
            problem_response(
                status_code,
                detail,
                title=title,
                request=context.request,
            )
        )


gateway_reference = RabbitMqTransport()
gateway_rabbit = RabbitMqModule.for_root(RabbitMqOptions(rabbitmq_url()))
gateway_clients = ClientsModule.register_cluster(
    gateway_reference,
    imports=(gateway_rabbit,),
    contracts=(CatalogService, OrdersService, NotificationsService),
)


@module(
    imports=(gateway_clients,),
    providers=(
        ValueProvider("validation", MsgspecValidationPipe()),
        ValueProvider("gateway-errors", GatewayErrorFilter()),
    ),
    controllers=(GatewayController,),
)
class GatewayAppModule:
    """HTTP-only root; it deliberately has no service runtime or database."""


async def create_application() -> NestApplication:
    application = await NestApplication.create(
        GatewayAppModule,
        adapter=StarletteAdapter(),
    )
    application.use_global_pipe("validation")
    application.use_global_filter("gateway-errors")
    return application


def application_factory() -> object:
    """Expose a factory for the ASGI runner without opening resources on import."""

    from nestpy.starlette import asgi

    return asgi(create_application)


application = application_factory()
