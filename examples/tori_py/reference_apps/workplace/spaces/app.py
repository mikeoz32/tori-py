"""Spaces service owns tenant-scoped offices, floors, and resources."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Annotated
from uuid import uuid4

from sqlalchemy import Integer, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from tori_py import NestApplication, controller, module
from tori_py_cqrs import CqrsModule, command_handler, query_handler
from tori_py_cqrs_core import Command, CommandBus, Query, QueryBus
from tori_py_microservices import Payload, PublicRpcError, rpc
from tori_py_sqlalchemy import EntityManager, Repository, SqlAlchemyModule, repository

from ..common.contracts import (
    CreateResourceRpc,
    GetResource,
    Health,
    ListResources,
    Principal,
    Resource,
)
from ..common.infrastructure import rabbit_modules, serve, sql_module
from ..common.security import has_workplace_role, is_facilities_admin
from ..common.services import SPACES, SpacesService

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class ResourceRow(Base):
    __tablename__ = "resources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    office_id: Mapped[str] = mapped_column(String(128))
    floor_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))
    x: Mapped[int] = mapped_column(Integer)
    y: Mapped[int] = mapped_column(Integer)


@repository(ResourceRow)
class ResourceRepository(Repository[ResourceRow]):
    async def tenant_resource(
        self, tenant_id: str, resource_id: str
    ) -> ResourceRow | None:
        return await self.find_one(
            ResourceRow.tenant_id == tenant_id, ResourceRow.id == resource_id
        )


@dataclass(frozen=True, slots=True)
class CreateResourceCommand(Command[Resource]):
    tenant_id: str
    office_id: str
    floor_id: str
    name: str
    kind: str
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class GetResourceQuery(Query[Resource]):
    tenant_id: str
    resource_id: str


@dataclass(frozen=True, slots=True)
class ListResourcesQuery(Query[list[Resource]]):
    tenant_id: str
    floor_id: str | None


@command_handler(CreateResourceCommand)
class CreateResourceHandler:
    def __init__(self, entities: EntityManager, resources: ResourceRepository) -> None:
        self._entities, self._resources = entities, resources

    async def handle(self, command: CreateResourceCommand) -> Resource:
        if command.kind not in {"desk", "room"} or not all(
            0 <= point <= 1000 for point in (command.x, command.y)
        ):
            raise ValueError("resource kind and geometry are invalid")
        async with self._entities.transaction():
            row = await self._resources.add(
                ResourceRow(
                    id=str(uuid4()),
                    tenant_id=command.tenant_id,
                    office_id=command.office_id,
                    floor_id=command.floor_id,
                    name=command.name,
                    kind=command.kind,
                    x=command.x,
                    y=command.y,
                )
            )
            return _resource(row)


@query_handler(GetResourceQuery)
class GetResourceHandler:
    def __init__(self, resources: ResourceRepository) -> None:
        self._resources = resources

    async def handle(self, query: GetResourceQuery) -> Resource:
        row = await self._resources.tenant_resource(query.tenant_id, query.resource_id)
        if row is None:
            raise LookupError("resource was not found")
        return _resource(row)


@query_handler(ListResourcesQuery)
class ListResourcesHandler:
    def __init__(self, resources: ResourceRepository) -> None:
        self._resources = resources

    async def handle(self, query: ListResourcesQuery) -> list[Resource]:
        filters = [ResourceRow.tenant_id == query.tenant_id]
        if query.floor_id is not None:
            filters.append(ResourceRow.floor_id == query.floor_id)
        return [_resource(row) for row in await self._resources.find(*filters)]


@controller()
class SpacesController:
    def __init__(
        self, commands: CommandBus, queries: QueryBus, entities: EntityManager
    ) -> None:
        self._commands, self._queries, self._entities = commands, queries, entities

    @rpc(SpacesService.create_resource)
    async def create_resource(
        self, payload: Annotated[CreateResourceRpc, Payload()]
    ) -> Resource:
        if not is_facilities_admin(payload.principal):
            raise PublicRpcError(
                "forbidden", "Facilities administrator role is required."
            )
        item = payload.resource
        return await self._commands.execute(
            CreateResourceCommand(
                payload.principal.tenant_id,
                item.office_id,
                item.floor_id,
                item.name,
                item.kind,
                item.x,
                item.y,
            )
        )

    @rpc(SpacesService.get_resource)
    async def get_resource(
        self, payload: Annotated[GetResource, Payload()]
    ) -> Resource:
        _require_workplace_role(payload.principal)
        try:
            return await self._queries.execute(
                GetResourceQuery(payload.principal.tenant_id, payload.resource_id)
            )
        except LookupError as error:
            raise PublicRpcError("not_found", "Resource was not found.") from error

    @rpc(SpacesService.list_resources)
    async def list_resources(
        self, payload: Annotated[ListResources, Payload()]
    ) -> list[Resource]:
        _require_workplace_role(payload.principal)
        try:
            return await self._queries.execute(
                ListResourcesQuery(payload.principal.tenant_id, payload.floor_id)
            )
        except Exception:
            logger.exception("resource listing failed")
            raise

    @rpc(SpacesService.health)
    async def health(self, payload: Annotated[Health, Payload()]) -> dict[str, str]:
        del payload
        await self._entities.scalar(select(1))
        return {"status": "ok"}


spaces_sql = sql_module("spaces")
spaces_feature = SqlAlchemyModule.for_feature([ResourceRepository])
_, spaces_rabbit, spaces_service = rabbit_modules(SPACES)
cqrs = CqrsModule.for_root(global_=True)


@module(
    imports=(spaces_sql, spaces_feature, cqrs, spaces_service),
    providers=(CreateResourceHandler, GetResourceHandler, ListResourcesHandler),
    controllers=(SpacesController,),
)
class SpacesAppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(SpacesAppModule)


async def run() -> None:
    await serve(create_application)


def _resource(row: ResourceRow) -> Resource:
    return Resource(
        row.id,
        row.tenant_id,
        row.office_id,
        row.floor_id,
        row.name,
        row.kind,
        row.x,
        row.y,
    )


def _require_workplace_role(principal: Principal) -> None:
    if not has_workplace_role(principal):
        raise PublicRpcError("forbidden", "A workplace role is required.")


if __name__ == "__main__":
    asyncio.run(run())
