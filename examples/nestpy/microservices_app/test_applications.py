"""Composition acceptance tests for the four application roots."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import msgspec
import pytest
from nestpy.http import HttpException
from nestpy.starlette import RequestContext
from nestpy_sqlalchemy import EntityManager
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.responses import Response

from examples.nestpy.microservices_app.catalog.app import (
    Base as CatalogBase,
)
from examples.nestpy.microservices_app.catalog.app import (
    CatalogItemRow,
    CatalogRepository,
    CreateItemCommand,
    CreateItemHandler,
)
from examples.nestpy.microservices_app.catalog.app import (
    IdempotencyConflictError as CatalogIdempotencyConflictError,
)
from examples.nestpy.microservices_app.catalog.app import (
    create_application as create_catalog_application,
)
from examples.nestpy.microservices_app.common.contracts import (
    CatalogItem,
    CreateCatalogItem,
    CreateOrder,
    ListNotifications,
    OrderCreated,
)
from examples.nestpy.microservices_app.gateway.app import (
    GatewayErrorFilter,
    _validate_idempotency_key,
)
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
    IdempotencyConflictError as OrderIdempotencyConflictError,
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
from nestpy_microservices import (
    RabbitMqConnectionError,
    RemoteRpcError,
    RpcProtocolError,
)


@pytest.mark.parametrize(
    ("payload", "contract"),
    (
        ({"name": "\x00", "price_cents": 1}, CreateCatalogItem),
        ({"item_id": 1, "quantity": 2_147_483_648}, CreateOrder),
    ),
)
def test_write_contracts_reject_values_postgres_cannot_store(
    payload: dict[str, object],
    contract: type[object],
) -> None:
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert(payload, type=contract)


@pytest.mark.parametrize("value", ("", " ", "x" * 121, "bad\x00key"))
def test_gateway_rejects_invalid_idempotency_keys(value: str) -> None:
    with pytest.raises(HttpException) as caught:
        _validate_idempotency_key(value)

    assert caught.value.status_code == 400


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
async def test_create_item_is_idempotent_and_binds_the_key_to_its_payload() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(CatalogBase.metadata.create_all)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    items = CatalogRepository(CatalogItemRow, entities)
    handler = CreateItemHandler(entities, items)
    command = CreateItemCommand("Keyboard", 9900, "same-request")
    try:
        first = await handler.handle(command)
        second = await handler.handle(command)
        with pytest.raises(CatalogIdempotencyConflictError):
            await handler.handle(CreateItemCommand("Keyboard", 12000, "same-request"))
        async with entities.transaction():
            item_count = await items.count()
    finally:
        await engine.dispose()

    assert second == first
    assert item_count == 1


@pytest.mark.asyncio
async def test_place_order_is_idempotent_with_one_atomic_outbox_record() -> None:
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
        command = PlaceOrderCommand(1, 2, "same-request")
        first = await handler.handle(command)
        second = await handler.handle(command)
        with pytest.raises(OrderIdempotencyConflictError):
            await handler.handle(PlaceOrderCommand(1, 3, "same-request"))
        async with entities.transaction():
            order_count = await orders.count()
            outbox_count = await outbox.count()
    finally:
        await engine.dispose()

    assert second == first
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
        async with entities.transaction():
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
