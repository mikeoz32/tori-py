"""Orders service with local CQRS, catalog RPC, and an outbox relay."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import uuid4

from cqrs_core import Command, CommandBus, Query, QueryBus
from nestpy import AliasProvider, NestApplication, controller, injectable, module
from nestpy_cqrs import CqrsModule, command_handler, query_handler
from nestpy_sqlalchemy import EntityManager, Repository, SqlAlchemyModule, repository
from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from examples.nestpy.microservices_app.common.contracts import (
    CreateOrder,
    GetOrder,
    Order,
)
from examples.nestpy.microservices_app.common.infrastructure import (
    database_url,
    rabbit_modules,
    serve,
    sql_module,
)
from examples.nestpy.microservices_app.common.services import (
    CatalogItemLookup,
    CatalogService,
    HealthCheck,
    OrdersService,
)
from nestpy_microservices import (
    ClientsModule,
    Context,
    EventDispatcher,
    Payload,
    PublicRpcError,
    RemoteRpcError,
    RpcContext,
    ServiceIdentity,
    rpc,
    utc_now,
)

SERVICE = ServiceIdentity("demo", "orders", 1)
CATALOG = ServiceIdentity("demo", "catalog", 1)
logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Orders-owned metadata."""


class OrderRow(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    item_id: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))


class OutboxRow(Base):
    __tablename__ = "outbox"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_name: Mapped[str] = mapped_column(String(120))
    payload: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


@repository(OrderRow)
class OrderRepository(Repository[OrderRow]):
    async def find_by_idempotency_key(self, key: str) -> OrderRow | None:
        return await self.find_one(OrderRow.idempotency_key == key)


@repository(OutboxRow)
class OutboxRepository(Repository[OutboxRow]):
    async def next_pending(self) -> OutboxRow | None:
        rows = await self.find(
            OutboxRow.published_at.is_(None),
            order_by=(OutboxRow.attempts, OutboxRow.event_id),
            limit=1,
        )
        return rows[0] if rows else None


@dataclass(frozen=True, slots=True)
class PlaceOrderCommand(Command[Order]):
    item_id: int
    quantity: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class GetOrderQuery(Query[Order]):
    order_id: int


class IdempotencyConflictError(Exception):
    """An idempotency key was reused for a different order request."""


@command_handler(PlaceOrderCommand)
class PlaceOrderHandler:
    def __init__(
        self,
        entities: EntityManager,
        orders: OrderRepository,
        outbox: OutboxRepository,
        catalog: CatalogItemLookup,
    ) -> None:
        self._entities = entities
        self._orders = orders
        self._outbox = outbox
        self._catalog = catalog

    async def handle(self, command: PlaceOrderCommand) -> Order:
        if command.quantity <= 0:
            raise ValueError("quantity must be positive")
        async with self._entities.transaction():
            existing = await self._orders.find_by_idempotency_key(
                command.idempotency_key
            )
            if existing is not None:
                return _replayed_order(existing, command)
        item = await self._catalog.get_item(command.item_id)
        try:
            async with self._entities.transaction():
                row = await self._orders.add(
                    OrderRow(
                        idempotency_key=command.idempotency_key,
                        item_id=item.id,
                        quantity=command.quantity,
                        unit_price_cents=item.price_cents,
                        status="created",
                    )
                )
                order = _to_contract(row)
                await self._outbox.add(
                    OutboxRow(
                        event_id=str(uuid4()),
                        event_name="order-created",
                        payload=json.dumps(
                            {
                                "order_id": order.id,
                                "item_id": order.item_id,
                                "quantity": order.quantity,
                                "total_cents": (
                                    order.quantity * order.unit_price_cents
                                ),
                            },
                            separators=(",", ":"),
                        ),
                    )
                )
                return order
        except IntegrityError:
            async with self._entities.transaction():
                existing = await self._orders.find_by_idempotency_key(
                    command.idempotency_key
                )
                if existing is None:
                    raise
                return _replayed_order(existing, command)


@query_handler(GetOrderQuery)
class GetOrderHandler:
    def __init__(self, entities: EntityManager, orders: OrderRepository) -> None:
        self._entities = entities
        self._orders = orders

    async def handle(self, query: GetOrderQuery) -> Order:
        async with self._entities.transaction():
            row = await self._orders.get(query.order_id)
            if row is None:
                raise LookupError(f"order {query.order_id} was not found")
            return _to_contract(row)


@injectable()
class OutboxRelay:
    """At-least-once relay with duplicate-safe downstream consumers."""

    def __init__(
        self,
        entities: EntityManager,
        outbox: OutboxRepository,
        events: EventDispatcher,
    ) -> None:
        self._entities = entities
        self._outbox = outbox
        self._events = events
        self._task: asyncio.Task[object] | None = None

    async def on_application_bootstrap(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def on_application_shutdown(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                published = await self.publish_once()
                if not published:
                    await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("outbox publication failed; retrying")
                await asyncio.sleep(0.5)

    async def publish_once(self) -> bool:
        async with self._entities.transaction():
            row = await self._outbox.next_pending()
            if row is None:
                return False
            event_id = row.event_id
            event_name = row.event_name
            payload = json.loads(row.payload)
            row.attempts += 1
            await self._entities.flush()
        await self._events.publish(
            event_name,
            1,
            payload,
            headers={"outbox_event_id": event_id},
            require_route=True,
        )
        async with self._entities.transaction():
            published = await self._outbox.get(event_id)
            if published is not None:
                published.published_at = utc_now()
                await self._entities.flush()
        return True


@controller()
class OrdersController:
    def __init__(
        self,
        commands: CommandBus,
        queries: QueryBus,
        entities: EntityManager,
    ) -> None:
        self._commands = commands
        self._queries = queries
        self._entities = entities

    @rpc(OrdersService.create_order)
    async def create_order(
        self,
        payload: Annotated[CreateOrder, Payload()],
        context: Annotated[RpcContext, Context()],
    ) -> Order:
        idempotency_key = context.idempotency_key
        if (
            idempotency_key is None
            or not idempotency_key.strip()
            or len(idempotency_key) > 120
            or "\x00" in idempotency_key
        ):
            raise PublicRpcError(
                "invalid_request", "create-order requires a valid idempotency key."
            )
        try:
            return await self._commands.execute(
                PlaceOrderCommand(
                    payload.item_id,
                    payload.quantity,
                    idempotency_key,
                )
            )
        except IdempotencyConflictError as error:
            raise PublicRpcError(
                "conflict", "The idempotency key was used for another request."
            ) from error
        except ValueError as error:
            raise PublicRpcError(
                "invalid_request", "Order quantity must be positive."
            ) from error
        except RemoteRpcError as error:
            raise PublicRpcError(
                error.code,
                error.message,
                retryable=error.retryable,
                details=error.details,
            ) from error

    @rpc(OrdersService.get_order)
    async def get_order(
        self,
        payload: Annotated[GetOrder, Payload()],
    ) -> Order:
        try:
            return await self._queries.execute(GetOrderQuery(payload.order_id))
        except LookupError as error:
            raise PublicRpcError("not_found", "Order was not found.") from error

    @rpc(OrdersService.health)
    async def health(
        self,
        payload: Annotated[HealthCheck, Payload()],
    ) -> dict[str, str]:
        del payload
        async with self._entities.transaction():
            await self._entities.scalar(select(1))
        return {"status": "ok"}


orders_sql = sql_module(database_url("orders"))
orders_feature = SqlAlchemyModule.for_feature([OrderRepository, OutboxRepository])
rabbit_reference, orders_rabbit, orders_service = rabbit_modules(SERVICE)
orders_clients = ClientsModule.register_cluster(
    rabbit_reference,
    imports=(orders_rabbit,),
    contracts=(CatalogService,),
)
cqrs = CqrsModule.for_root(global_=True)


@module(
    imports=(orders_sql, orders_feature, cqrs, orders_service, orders_clients),
    providers=(
        AliasProvider(CatalogItemLookup, CatalogService),
        PlaceOrderHandler,
        GetOrderHandler,
        OutboxRelay,
    ),
    controllers=(OrdersController,),
)
class OrdersAppModule:
    """Composition root for the orders service."""


async def create_application() -> NestApplication:
    return await NestApplication.create(OrdersAppModule)


async def run() -> None:
    await serve(create_application)


def _to_contract(row: OrderRow) -> Order:
    return Order(
        row.id,
        row.item_id,
        row.quantity,
        row.unit_price_cents,
        row.status,
    )


def _replayed_order(row: OrderRow, command: PlaceOrderCommand) -> Order:
    if row.item_id != command.item_id or row.quantity != command.quantity:
        raise IdempotencyConflictError
    return _to_contract(row)


if __name__ == "__main__":
    asyncio.run(run())
