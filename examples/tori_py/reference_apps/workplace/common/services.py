"""Typed RPC service contracts; principals are explicit RPC payload data."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from tori_py_microservices import ServiceIdentity, rpc_call, service_contract

from .contracts import (
    AdminRequest,
    AuditEntry,
    Availability,
    AvailabilityQuery,
    Booking,
    CancelBooking,
    CheckInBooking,
    CleanupOutbox,
    CreateBooking,
    CreateResource,
    CreateResourceRpc,
    FacilityDashboard,
    GetBooking,
    GetResource,
    Health,
    ListAudit,
    ListBookings,
    ListNotifications,
    ListResources,
    Notification,
    OutboxDiagnostics,
    Principal,
    Resource,
)

SPACES = ServiceIdentity("workplace", "spaces", 1)
BOOKINGS = ServiceIdentity("workplace", "bookings", 1)
NOTIFICATIONS = ServiceIdentity("workplace", "notifications", 1)


@service_contract(SPACES)
class SpacesService(Protocol):
    @rpc_call("create-resource", payload=CreateResourceRpc)
    async def create_resource(
        self, principal: Principal, resource: CreateResource
    ) -> Resource: ...
    @rpc_call("get-resource", payload=GetResource)
    async def get_resource(
        self, principal: Principal, resource_id: str
    ) -> Resource: ...
    @rpc_call("list-resources", payload=ListResources)
    async def list_resources(
        self, principal: Principal, floor_id: str | None = None
    ) -> list[Resource]: ...
    @rpc_call("health", payload=Health, timeout=2)
    async def health(self) -> dict[str, str]: ...


@service_contract(BOOKINGS)
class BookingsService(Protocol):
    @rpc_call("create-booking", payload=CreateBooking)
    async def create_booking(
        self,
        principal: Principal,
        resource_id: str,
        starts_at: datetime,
        ends_at: datetime,
        idempotency_key: str,
    ) -> Booking: ...
    @rpc_call("get-booking", payload=GetBooking)
    async def get_booking(self, principal: Principal, booking_id: str) -> Booking: ...
    @rpc_call("list-bookings", payload=ListBookings)
    async def list_bookings(
        self,
        principal: Principal,
        resource_id: str | None = None,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Booking]: ...
    @rpc_call("availability", payload=AvailabilityQuery)
    async def availability(
        self,
        principal: Principal,
        starts_at: datetime,
        ends_at: datetime,
        resource_id: str | None = None,
    ) -> list[Availability]: ...
    @rpc_call("facilities-dashboard", payload=AdminRequest)
    async def facilities_dashboard(self, principal: Principal) -> FacilityDashboard: ...
    @rpc_call("list-audit", payload=ListAudit)
    async def list_audit(
        self,
        principal: Principal,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
        resource_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]: ...
    @rpc_call("outbox-diagnostics", payload=AdminRequest)
    async def outbox_diagnostics(self, principal: Principal) -> OutboxDiagnostics: ...
    @rpc_call("cleanup-outbox", payload=CleanupOutbox)
    async def cleanup_outbox(self, principal: Principal, before: datetime) -> int: ...
    @rpc_call("cancel-booking", payload=CancelBooking)
    async def cancel_booking(
        self, principal: Principal, booking_id: str
    ) -> Booking: ...
    @rpc_call("check-in-booking", payload=CheckInBooking)
    async def check_in_booking(
        self, principal: Principal, booking_id: str
    ) -> Booking: ...
    @rpc_call("health", payload=Health, timeout=2)
    async def health(self) -> dict[str, str]: ...


@service_contract(NOTIFICATIONS)
class NotificationsService(Protocol):
    @rpc_call("list-notifications", payload=ListNotifications)
    async def list_notifications(
        self, principal: Principal, limit: int = 100
    ) -> list[Notification]: ...
    @rpc_call("health", payload=Health, timeout=2)
    async def health(self) -> dict[str, str]: ...
