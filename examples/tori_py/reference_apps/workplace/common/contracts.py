"""Stable, transport-safe contracts for the workplace services."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

import msgspec

type Identifier = Annotated[str, msgspec.Meta(min_length=1, max_length=128)]
type GeometryCoordinate = Annotated[int, msgspec.Meta(ge=0, le=1000)]


class Principal(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    tenant_id: Identifier
    actor_id: Identifier
    roles: tuple[str, ...] = ()


class ResourceKind(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    value: Literal["desk", "room"]


class Resource(msgspec.Struct, frozen=True):
    id: str
    tenant_id: str
    office_id: str
    floor_id: str
    name: str
    kind: str
    x: int
    y: int


class CreateResource(msgspec.Struct, forbid_unknown_fields=True):
    office_id: Identifier
    floor_id: Identifier
    name: Identifier
    kind: Literal["desk", "room"]
    x: GeometryCoordinate
    y: GeometryCoordinate


class CreateResourceRequest(CreateResource, forbid_unknown_fields=True):
    """Browser input; identity is deliberately not client supplied."""


class CreateResourceRpc(msgspec.Struct, forbid_unknown_fields=True):
    principal: Principal
    resource: CreateResource


class GetResource(msgspec.Struct, forbid_unknown_fields=True):
    principal: Principal
    resource_id: Identifier


class ListResources(msgspec.Struct, forbid_unknown_fields=True):
    principal: Principal
    floor_id: str | None = None


class Booking(msgspec.Struct, frozen=True):
    id: str
    tenant_id: str
    actor_id: str
    resource_id: str
    starts_at: datetime
    ends_at: datetime
    status: str
    idempotency_key: str


class CreateBookingRequest(msgspec.Struct, forbid_unknown_fields=True):
    resource_id: Identifier
    starts_at: datetime
    ends_at: datetime


class CreateBooking(msgspec.Struct, forbid_unknown_fields=True):
    principal: Principal
    resource_id: Identifier
    starts_at: datetime
    ends_at: datetime
    idempotency_key: Identifier


class GetBooking(msgspec.Struct, forbid_unknown_fields=True):
    principal: Principal
    booking_id: Identifier


class ListBookings(msgspec.Struct, forbid_unknown_fields=True):
    principal: Principal
    resource_id: str | None = None


class CancelBooking(GetBooking):
    pass


class CheckInBooking(GetBooking):
    pass


class BookingCreated(msgspec.Struct, frozen=True):
    tenant_id: str
    booking_id: str
    actor_id: str
    resource_id: str


class Notification(msgspec.Struct, frozen=True):
    id: str
    tenant_id: str
    event_id: str
    message: str
    created_at: datetime


class ListNotifications(msgspec.Struct, forbid_unknown_fields=True):
    principal: Principal
    limit: Annotated[int, msgspec.Meta(ge=1, le=100)] = 100


class Health(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    pass
