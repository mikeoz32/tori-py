"""Catalog service with PostgreSQL persistence and local CQRS."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated

from cqrs_core import Command, CommandBus, Query, QueryBus
from nestpy import NestApplication, controller, module
from nestpy_cqrs import CqrsModule, command_handler, query_handler
from nestpy_sqlalchemy import EntityManager, Repository, SqlAlchemyModule, repository
from sqlalchemy import String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from examples.nestpy.microservices_app.common.contracts import (
    CatalogItem,
    CreateCatalogItem,
    GetCatalogItem,
)
from examples.nestpy.microservices_app.common.infrastructure import (
    database_url,
    rabbit_modules,
    serve,
    sql_module,
)
from examples.nestpy.microservices_app.common.services import (
    CatalogService,
    HealthCheck,
)
from nestpy_microservices import (
    Payload,
    PublicRpcError,
    ServiceIdentity,
    rpc,
)

SERVICE = ServiceIdentity("demo", "catalog", 1)


class Base(DeclarativeBase):
    """Catalog-owned metadata."""


class CatalogItemRow(Base):
    __tablename__ = "catalog_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    price_cents: Mapped[int] = mapped_column()


@repository(CatalogItemRow)
class CatalogRepository(Repository[CatalogItemRow]):
    pass


@dataclass(frozen=True, slots=True)
class CreateItemCommand(Command[CatalogItem]):
    name: str
    price_cents: int


@dataclass(frozen=True, slots=True)
class GetItemQuery(Query[CatalogItem]):
    item_id: int


@command_handler(CreateItemCommand)
class CreateItemHandler:
    def __init__(self, items: CatalogRepository) -> None:
        self._items = items

    async def handle(self, command: CreateItemCommand) -> CatalogItem:
        name = command.name.strip()
        if not name or command.price_cents <= 0:
            raise ValueError("name and positive price_cents are required")
        row = await self._items.add(
            CatalogItemRow(name=name, price_cents=command.price_cents)
        )
        return _to_contract(row)


@query_handler(GetItemQuery)
class GetItemHandler:
    def __init__(self, items: CatalogRepository) -> None:
        self._items = items

    async def handle(self, query: GetItemQuery) -> CatalogItem:
        row = await self._items.get(query.item_id)
        if row is None:
            raise LookupError(f"catalog item {query.item_id} was not found")
        return _to_contract(row)


@controller()
class CatalogController:
    """RPC boundary; the gateway never sees the ORM row."""

    def __init__(
        self,
        commands: CommandBus,
        queries: QueryBus,
        entities: EntityManager,
    ) -> None:
        self._commands = commands
        self._queries = queries
        self._entities = entities

    @rpc(CatalogService.create_item)
    async def create_item(
        self,
        payload: Annotated[CreateCatalogItem, Payload()],
    ) -> CatalogItem:
        try:
            return await self._commands.execute(
                CreateItemCommand(payload.name, payload.price_cents)
            )
        except ValueError as error:
            raise PublicRpcError(
                "invalid_request", "Name and positive price_cents are required."
            ) from error
        except IntegrityError as error:
            raise PublicRpcError(
                "conflict", "A catalog item with this name already exists."
            ) from error

    @rpc(CatalogService.get_item)
    async def get_item(
        self,
        payload: Annotated[GetCatalogItem, Payload()],
    ) -> CatalogItem:
        try:
            return await self._queries.execute(GetItemQuery(payload.item_id))
        except LookupError as error:
            raise PublicRpcError("not_found", "Catalog item was not found.") from error

    @rpc(CatalogService.health)
    async def health(
        self,
        payload: Annotated[HealthCheck, Payload()],
    ) -> dict[str, str]:
        del payload
        await self._entities.scalar(select(1))
        return {"status": "ok"}


catalog_sql = sql_module(database_url("catalog"))
catalog_feature = SqlAlchemyModule.for_feature([CatalogRepository])
_, catalog_rabbit, catalog_service = rabbit_modules(SERVICE)
cqrs = CqrsModule.for_root(global_=True)


@module(
    imports=(catalog_sql, catalog_feature, cqrs, catalog_service),
    providers=(CreateItemHandler, GetItemHandler),
    controllers=(CatalogController,),
)
class CatalogAppModule:
    """Composition root for one catalog service identity."""


async def create_application() -> NestApplication:
    return await NestApplication.create(CatalogAppModule)


async def run() -> None:
    await serve(create_application)


def _to_contract(row: CatalogItemRow) -> CatalogItem:
    return CatalogItem(row.id, row.name, row.price_cents)


if __name__ == "__main__":
    asyncio.run(run())
