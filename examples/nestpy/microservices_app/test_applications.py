"""Composition acceptance tests for the four application roots."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from nestpy.starlette import RequestContext
from nestpy_microservices import (
    RabbitMqConnectionError,
    RemoteRpcError,
    RpcProtocolError,
)
from nestpy_sqlalchemy import EntityManager
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.responses import Response

from examples.nestpy.microservices_app.catalog.app import (
    create_application as create_catalog_application,
)
from examples.nestpy.microservices_app.common.contracts import (
    CatalogItem,
    ListNotifications,
    OrderCreated,
)
from examples.nestpy.microservices_app.gateway.app import GatewayErrorFilter
from examples.nestpy.microservices_app.gateway.app import (
    create_application as create_gateway_application,
)
from examples.nestpy.microservices_app.notifications.app import (
    Base as NotificationsBase,
)
from examples.nestpy.microservices_app.notifications.app import (
    NotificationRepository,
    NotificationRow,
    NotificationsController,
)
from examples.nestpy.microservices_app.notifications.app import (
    create_application as create_notifications_application,
)
from examples.nestpy.microservices_app.orders.app import (
    Base as OrdersBase,
)
from examples.nestpy.microservices_app.orders.app import (
    OrderRepository,
    OrderRow,
    OutboxRepository,
    OutboxRow,
    PlaceOrderCommand,
    PlaceOrderHandler,
)
from examples.nestpy.microservices_app.orders.app import (
    create_application as create_orders_application,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory",
    (
        create_catalog_application,
        create_orders_application,
        create_notifications_application,
        create_gateway_application,
    ),
)
async def test_each_process_has_one_compiled_application_root(factory) -> None:
    application = await factory()
    assert application.state.value == "compiled"


class FakeCatalogService:
    async def get_item(self, item_id: int) -> CatalogItem:
        return CatalogItem(item_id, "Keyboard", 9900)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_place_order_creates_one_atomic_outbox_record() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(OrdersBase.metadata.create_all)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    orders = OrderRepository(OrderRow, entities)
    outbox = OutboxRepository(OutboxRow, entities)
    handler = PlaceOrderHandler(
        entities,
        orders,
        outbox,
        FakeCatalogService(),
    )
    try:
        order = await handler.handle(PlaceOrderCommand(1, 2))
        order_count = await orders.count()
        outbox_count = await outbox.count()
    finally:
        await engine.dispose()

    assert order.item_id == 1
    assert order_count == 1
    assert outbox_count == 1


@pytest.mark.asyncio
async def test_notification_consumer_deduplicates_and_lists_newest_first() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(NotificationsBase.metadata.create_all)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    repository = NotificationRepository(NotificationRow, entities)
    controller = NotificationsController(entities, repository)
    event = OrderCreated(1, 1, 2, 19800)
    try:
        await controller.order_created(event, "event-1")
        await controller.order_created(event, "event-1")
        await controller.order_created(OrderCreated(2, 1, 1, 9900), "event-2")
        newest = await controller.list_notifications(ListNotifications(1))
        count = await repository.count()
    finally:
        await engine.dispose()

    assert count == 2
    assert newest[0].event_id == "event-2"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code"),
    (
        (
            RemoteRpcError(
                "not_found",
                "Catalog item was not found.",
                retryable=False,
            ),
            404,
        ),
        (RabbitMqConnectionError("connection unavailable"), 503),
        (RpcProtocolError("invalid response"), 502),
    ),
)
async def test_gateway_filter_maps_stable_errors(
    error: Exception,
    status_code: int,
) -> None:
    context = cast(RequestContext, SimpleNamespace(request=None))

    result = await GatewayErrorFilter().catch(error, context)

    assert result.is_response
    assert cast(Response, result.value).status_code == status_code
