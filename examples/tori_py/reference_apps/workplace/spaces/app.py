"""Spaces service owns tenant-scoped offices, floors, and resources."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import time
from typing import Annotated
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    Boolean,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    exists,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from tori_py import NestApplication, controller, module
from tori_py_cqrs import CqrsModule, command_handler, query_handler
from tori_py_cqrs_core import Command, CommandBus, Query, QueryBus
from tori_py_microservices import Payload, PublicRpcError, rpc
from tori_py_sqlalchemy import EntityManager, Repository, SqlAlchemyModule, repository

from ..common.contracts import (
    MAX_RESOURCE_OFFSET,
    CreateResourceRpc,
    GetOfficePolicy,
    GetResource,
    GetResources,
    Health,
    ListResources,
    OfficePolicy,
    OfficePolicyUpdate,
    Principal,
    Resource,
    UpdateOfficePolicyRpc,
    UpdateResourceRpc,
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
    equipment_json: Mapped[str] = mapped_column(Text, default="[]")
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ResourceEquipmentRow(Base):
    __tablename__ = "resource_equipment"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), primary_key=True)


class OfficePolicyRow(Base):
    __tablename__ = "office_policies"
    __table_args__ = (UniqueConstraint("tenant_id", "office_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    office_id: Mapped[str] = mapped_column(String(128))
    time_zone: Mapped[str] = mapped_column(String(128))
    opens_at_minute: Mapped[int] = mapped_column(Integer)
    closes_at_minute: Mapped[int] = mapped_column(Integer)
    weekdays_json: Mapped[str] = mapped_column(Text)


@repository(ResourceRow)
class ResourceRepository(Repository[ResourceRow]):
    async def tenant_resource(
        self, tenant_id: str, resource_id: str
    ) -> ResourceRow | None:
        return await self.find_one(
            ResourceRow.tenant_id == tenant_id, ResourceRow.id == resource_id
        )


@repository(ResourceEquipmentRow)
class ResourceEquipmentRepository(Repository[ResourceEquipmentRow]):
    pass


@repository(OfficePolicyRow)
class OfficePolicyRepository(Repository[OfficePolicyRow]):
    async def tenant_policy(
        self, tenant_id: str, office_id: str, *, for_update: bool = False
    ) -> OfficePolicyRow | None:
        return await self.find_one(
            OfficePolicyRow.tenant_id == tenant_id,
            OfficePolicyRow.office_id == office_id,
            with_for_update=for_update,
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
    equipment: tuple[str, ...] = ()
    capacity: int = 1


@dataclass(frozen=True, slots=True)
class UpdateResourceCommand(Command[Resource]):
    tenant_id: str
    resource_id: str
    office_id: str | None = None
    floor_id: str | None = None
    name: str | None = None
    kind: str | None = None
    x: int | None = None
    y: int | None = None
    equipment: tuple[str, ...] | None = None
    capacity: int | None = None
    active: bool | None = None


@dataclass(frozen=True, slots=True)
class GetResourceQuery(Query[Resource]):
    tenant_id: str
    resource_id: str


@dataclass(frozen=True, slots=True)
class GetResourcesQuery(Query[list[Resource]]):
    tenant_id: str
    resource_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ListResourcesQuery(Query[list[Resource]]):
    tenant_id: str
    floor_id: str | None = None
    office_id: str | None = None
    kind: str | None = None
    equipment: tuple[str, ...] = ()
    min_capacity: int | None = None
    include_inactive: bool = False
    offset: int = 0
    limit: int = 50


@dataclass(frozen=True, slots=True)
class GetOfficePolicyQuery(Query[OfficePolicy]):
    tenant_id: str
    office_id: str


@dataclass(frozen=True, slots=True)
class UpdateOfficePolicyCommand(Command[OfficePolicy]):
    tenant_id: str
    office_id: str
    policy: OfficePolicyUpdate


@command_handler(CreateResourceCommand)
class CreateResourceHandler:
    def __init__(
        self,
        entities: EntityManager,
        resources: ResourceRepository,
        equipment: ResourceEquipmentRepository,
    ) -> None:
        self._entities, self._resources, self._equipment = (
            entities,
            resources,
            equipment,
        )

    async def handle(self, command: CreateResourceCommand) -> Resource:
        _validate_resource(command.kind, command.x, command.y, command.capacity)
        equipment = _normalize_equipment(command.equipment)
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
                    equipment_json=json.dumps(equipment),
                    capacity=command.capacity,
                )
            )
            for name in equipment:
                await self._equipment.add(
                    ResourceEquipmentRow(
                        tenant_id=command.tenant_id, resource_id=row.id, name=name
                    )
                )
            return _resource(row)


@command_handler(UpdateResourceCommand)
class UpdateResourceHandler:
    def __init__(
        self,
        entities: EntityManager,
        resources: ResourceRepository,
        resource_equipment: ResourceEquipmentRepository,
    ) -> None:
        self._entities, self._resources, self._resource_equipment = (
            entities,
            resources,
            resource_equipment,
        )

    async def handle(self, command: UpdateResourceCommand) -> Resource:
        _validate_resource(
            command.kind, command.x, command.y, command.capacity, partial=True
        )
        equipment = (
            _normalize_equipment(command.equipment)
            if command.equipment is not None
            else None
        )
        async with self._entities.transaction():
            row = await self._resources.tenant_resource(
                command.tenant_id, command.resource_id
            )
            if row is None:
                raise LookupError("resource was not found")
            for field in (
                "office_id",
                "floor_id",
                "name",
                "kind",
                "x",
                "y",
                "capacity",
                "active",
            ):
                value = getattr(command, field)
                if value is not None:
                    setattr(row, field, value)
            if equipment is not None:
                row.equipment_json = json.dumps(equipment)
                await self._entities.execute(
                    delete(ResourceEquipmentRow).where(
                        ResourceEquipmentRow.tenant_id == command.tenant_id,
                        ResourceEquipmentRow.resource_id == row.id,
                    )
                )
                for name in equipment:
                    await self._resource_equipment.add(
                        ResourceEquipmentRow(
                            tenant_id=command.tenant_id,
                            resource_id=row.id,
                            name=name,
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


@query_handler(GetResourcesQuery)
class GetResourcesHandler:
    def __init__(self, resources: ResourceRepository) -> None:
        self._resources = resources

    async def handle(self, query: GetResourcesQuery) -> list[Resource]:
        if not query.resource_ids:
            return []
        if len(query.resource_ids) > 100:
            raise ValueError("resource batch exceeds the supported size")
        rows = await self._resources.find(
            ResourceRow.tenant_id == query.tenant_id,
            ResourceRow.id.in_(query.resource_ids),
            order_by=(ResourceRow.id,),
        )
        return [_resource(row) for row in rows]


@query_handler(ListResourcesQuery)
class ListResourcesHandler:
    def __init__(self, resources: ResourceRepository) -> None:
        self._resources = resources

    async def handle(self, query: ListResourcesQuery) -> list[Resource]:
        filters = [ResourceRow.tenant_id == query.tenant_id]
        if query.office_id is not None:
            filters.append(ResourceRow.office_id == query.office_id)
        if query.floor_id is not None:
            filters.append(ResourceRow.floor_id == query.floor_id)
        if query.kind is not None:
            if query.kind not in {"desk", "room"}:
                raise ValueError("resource kind is invalid")
            filters.append(ResourceRow.kind == query.kind)
        if query.min_capacity is not None:
            if not 1 <= query.min_capacity <= 1000:
                raise ValueError("resource capacity is invalid")
            filters.append(ResourceRow.capacity >= query.min_capacity)
        if not query.include_inactive:
            filters.append(ResourceRow.active.is_(True))
        equipment = _normalize_equipment(query.equipment)
        if not 0 <= query.offset <= MAX_RESOURCE_OFFSET or not 1 <= query.limit <= 100:
            raise ValueError("resource page is outside the supported range")
        for name in equipment:
            filters.append(
                exists(
                    select(ResourceEquipmentRow.name).where(
                        ResourceEquipmentRow.tenant_id == ResourceRow.tenant_id,
                        ResourceEquipmentRow.resource_id == ResourceRow.id,
                        ResourceEquipmentRow.name == name,
                    )
                )
            )
        return [
            _resource(row)
            for row in await self._resources.find(
                *filters,
                order_by=(ResourceRow.id,),
                offset=query.offset,
                limit=query.limit,
            )
        ]


@query_handler(GetOfficePolicyQuery)
class GetOfficePolicyHandler:
    def __init__(self, policies: OfficePolicyRepository) -> None:
        self._policies = policies

    async def handle(self, query: GetOfficePolicyQuery) -> OfficePolicy:
        row = await self._policies.tenant_policy(query.tenant_id, query.office_id)
        if row is None:
            raise LookupError("office policy was not found")
        return _office_policy(row)


@command_handler(UpdateOfficePolicyCommand)
class UpdateOfficePolicyHandler:
    def __init__(
        self, entities: EntityManager, policies: OfficePolicyRepository
    ) -> None:
        self._entities, self._policies = entities, policies

    async def handle(self, command: UpdateOfficePolicyCommand) -> OfficePolicy:
        opens_at, closes_at, weekdays = _validate_office_policy(command.policy)
        async with self._entities.transaction():
            row = await self._policies.tenant_policy(
                command.tenant_id, command.office_id, for_update=True
            )
            if row is None:
                row = await self._policies.add(
                    OfficePolicyRow(
                        id=str(uuid4()),
                        tenant_id=command.tenant_id,
                        office_id=command.office_id,
                        time_zone=command.policy.time_zone,
                        opens_at_minute=opens_at,
                        closes_at_minute=closes_at,
                        weekdays_json=json.dumps(weekdays),
                    )
                )
            else:
                row.time_zone = command.policy.time_zone
                row.opens_at_minute = opens_at
                row.closes_at_minute = closes_at
                row.weekdays_json = json.dumps(weekdays)
            return _office_policy(row)


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
        try:
            return await self._commands.execute(
                CreateResourceCommand(
                    payload.principal.tenant_id,
                    item.office_id,
                    item.floor_id,
                    item.name,
                    item.kind,
                    item.x,
                    item.y,
                    item.equipment,
                    item.capacity,
                )
            )
        except ValueError as error:
            raise PublicRpcError("invalid_request", str(error)) from error

    @rpc(SpacesService.update_resource)
    async def update_resource(
        self, payload: Annotated[UpdateResourceRpc, Payload()]
    ) -> Resource:
        if not is_facilities_admin(payload.principal):
            raise PublicRpcError(
                "forbidden", "Facilities administrator role is required."
            )
        item = payload.resource
        try:
            return await self._commands.execute(
                UpdateResourceCommand(
                    payload.principal.tenant_id,
                    payload.resource_id,
                    item.office_id,
                    item.floor_id,
                    item.name,
                    item.kind,
                    item.x,
                    item.y,
                    item.equipment,
                    item.capacity,
                    item.active,
                )
            )
        except LookupError as error:
            raise PublicRpcError("not_found", "Resource was not found.") from error
        except ValueError as error:
            raise PublicRpcError("invalid_request", str(error)) from error

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
        if payload.include_inactive and not is_facilities_admin(payload.principal):
            raise PublicRpcError(
                "forbidden", "Facilities administrator role is required."
            )
        try:
            return await self._queries.execute(
                ListResourcesQuery(
                    payload.principal.tenant_id,
                    payload.floor_id,
                    payload.office_id,
                    payload.kind,
                    payload.equipment,
                    payload.min_capacity,
                    payload.include_inactive,
                    payload.offset,
                    payload.limit,
                )
            )
        except ValueError as error:
            raise PublicRpcError("invalid_request", str(error)) from error
        except Exception:
            logger.exception("resource listing failed")
            raise

    @rpc(SpacesService.get_resources)
    async def get_resources(
        self, payload: Annotated[GetResources, Payload()]
    ) -> list[Resource]:
        _require_workplace_role(payload.principal)
        try:
            return await self._queries.execute(
                GetResourcesQuery(payload.principal.tenant_id, payload.resource_ids)
            )
        except ValueError as error:
            raise PublicRpcError("invalid_request", str(error)) from error

    @rpc(SpacesService.get_office_policy)
    async def get_office_policy(
        self, payload: Annotated[GetOfficePolicy, Payload()]
    ) -> OfficePolicy:
        _require_workplace_role(payload.principal)
        try:
            return await self._queries.execute(
                GetOfficePolicyQuery(payload.principal.tenant_id, payload.office_id)
            )
        except LookupError as error:
            raise PublicRpcError("not_found", "Office policy was not found.") from error

    @rpc(SpacesService.update_office_policy)
    async def update_office_policy(
        self, payload: Annotated[UpdateOfficePolicyRpc, Payload()]
    ) -> OfficePolicy:
        if not is_facilities_admin(payload.principal):
            raise PublicRpcError(
                "forbidden", "Facilities administrator role is required."
            )
        try:
            return await self._commands.execute(
                UpdateOfficePolicyCommand(
                    payload.principal.tenant_id, payload.office_id, payload.policy
                )
            )
        except ValueError as error:
            raise PublicRpcError("invalid_request", str(error)) from error

    @rpc(SpacesService.health)
    async def health(self, payload: Annotated[Health, Payload()]) -> dict[str, str]:
        del payload
        await self._entities.scalar(select(1))
        return {"status": "ok"}


spaces_sql = sql_module("spaces")
spaces_feature = SqlAlchemyModule.for_feature(
    [ResourceRepository, ResourceEquipmentRepository, OfficePolicyRepository]
)
_, spaces_rabbit, spaces_service = rabbit_modules(SPACES)
cqrs = CqrsModule.for_root(global_=True)


@module(
    imports=(spaces_sql, spaces_feature, cqrs, spaces_service),
    providers=(
        CreateResourceHandler,
        UpdateResourceHandler,
        GetResourceHandler,
        GetResourcesHandler,
        ListResourcesHandler,
        GetOfficePolicyHandler,
        UpdateOfficePolicyHandler,
    ),
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
        tuple(sorted(_equipment(row))),
        row.capacity,
        row.active,
    )


def _equipment(row: ResourceRow) -> set[str]:
    return set(json.loads(row.equipment_json))


def _normalize_equipment(equipment: tuple[str, ...]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for token in equipment:
        token = token.strip().lower()
        if not token or len(token) > 128:
            raise ValueError("resource equipment is invalid")
        normalized.add(token)
    return tuple(sorted(normalized))


def _office_policy(row: OfficePolicyRow) -> OfficePolicy:
    return OfficePolicy(
        row.office_id,
        row.time_zone,
        _format_minute(row.opens_at_minute),
        _format_minute(row.closes_at_minute),
        tuple(json.loads(row.weekdays_json)),
    )


def _validate_office_policy(
    policy: OfficePolicyUpdate,
) -> tuple[int, int, tuple[int, ...]]:
    try:
        ZoneInfo(policy.time_zone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("office time zone is invalid") from error
    opens_at = _parse_time(policy.opens_at)
    closes_at = _parse_time(policy.closes_at)
    weekdays = tuple(sorted(set(policy.weekdays)))
    if opens_at >= closes_at:
        raise ValueError("office hours are invalid")
    if not weekdays or any(day < 0 or day > 6 for day in weekdays):
        raise ValueError("office weekdays are invalid")
    return opens_at, closes_at, weekdays


def _parse_time(value: str) -> int:
    try:
        hour_text, minute_text = value.split(":", maxsplit=1)
        parsed = time(int(hour_text), int(minute_text))
    except (TypeError, ValueError) as error:
        raise ValueError("office hours are invalid") from error
    if value != parsed.strftime("%H:%M"):
        raise ValueError("office hours are invalid")
    return parsed.hour * 60 + parsed.minute


def _format_minute(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def _validate_resource(
    kind: str | None,
    x: int | None,
    y: int | None,
    capacity: int | None,
    *,
    partial: bool = False,
) -> None:
    if kind is not None and kind not in {"desk", "room"}:
        raise ValueError("resource kind is invalid")
    if any(point is not None and not 0 <= point <= 1000 for point in (x, y)):
        raise ValueError("resource geometry is invalid")
    if capacity is not None and not 1 <= capacity <= 1000:
        raise ValueError("resource capacity is invalid")
    if not partial and (kind is None or x is None or y is None or capacity is None):
        raise ValueError("resource is incomplete")


def _require_workplace_role(principal: Principal) -> None:
    if not has_workplace_role(principal):
        raise PublicRpcError("forbidden", "A workplace role is required.")


if __name__ == "__main__":
    asyncio.run(run())
