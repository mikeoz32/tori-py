"""Tenant-isolated booking service with explicit idempotency semantics."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from typing import Annotated, Literal, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator
from tori_py import NestApplication, controller, injectable, module
from tori_py_cqrs import CqrsModule, command_handler, query_handler
from tori_py_cqrs_core import Command, CommandBus, Query, QueryBus
from tori_py_microservices import (
    ClientsModule,
    EventDispatcher,
    Payload,
    PublicRpcError,
    rpc,
    utc_now,
)
from tori_py_sqlalchemy import EntityManager, Repository, SqlAlchemyModule, repository

from ..common.contracts import (
    AdminRequest,
    AuditEntry,
    Availability,
    Booking,
    BookingCreated,
    BookingLifecycleEvent,
    BookingRescheduled,
    CancelBooking,
    CheckInBooking,
    CleanupOutbox,
    CreateBooking,
    CreateRecurringBooking,
    FacilityDashboard,
    GetBooking,
    Health,
    ListAudit,
    ListBookings,
    OfficePolicy,
    OutboxDiagnostics,
    Principal,
    RescheduleBooking,
)
from ..common.contracts import (
    AvailabilityQuery as AvailabilityPayload,
)
from ..common.infrastructure import rabbit_modules, serve, sql_module
from ..common.security import has_workplace_role, is_facilities_admin
from ..common.services import BOOKINGS, BookingsService, SpacesService

MAX_BOOKING_DURATION = timedelta(hours=24)
OUTBOX_CLAIM_LEASE = timedelta(minutes=2)
logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Bookings-owned metadata (portable to SQLite)."""


class UtcDateTime(TypeDecorator[datetime]):
    """Restore UTC tzinfo when SQLite returns naive timestamp values."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(
        self, value: datetime | None, dialect: object
    ) -> datetime | None:
        del dialect
        return None if value is None else _as_utc(value)


class BookingRow(Base):
    __tablename__ = "bookings"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128))
    resource_id: Mapped[str] = mapped_column(String(128), index=True)
    starts_at: Mapped[datetime] = mapped_column(UtcDateTime())
    ends_at: Mapped[datetime] = mapped_column(UtcDateTime())
    status: Mapped[str] = mapped_column(String(16), default="booked")
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    series_id: Mapped[str | None] = mapped_column(String(36), index=True)
    occurrence_index: Mapped[int | None] = mapped_column(Integer)


class BookingOperationRow(Base):
    """Durable idempotency record for mutations of an existing booking."""

    __tablename__ = "booking_operations"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    booking_id: Mapped[str] = mapped_column(String(36), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    result_starts_at: Mapped[datetime] = mapped_column(UtcDateTime())
    result_ends_at: Mapped[datetime] = mapped_column(UtcDateTime())


class BookingSeriesRow(Base):
    """Idempotency and ownership record for a materialized booking series."""

    __tablename__ = "booking_series"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))


class BookingCancellationOperationRow(Base):
    """Durable result of one scoped cancellation request."""

    __tablename__ = "booking_cancellation_operations"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    result_booking_ids_json: Mapped[str] = mapped_column(Text)


class OutboxRow(Base):
    __tablename__ = "outbox"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_name: Mapped[str] = mapped_column(String(120))
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_token: Mapped[str | None] = mapped_column(String(36))
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditRow(Base):
    __tablename__ = "booking_audit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    booking_id: Mapped[str] = mapped_column(String(36), index=True)
    resource_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@repository(BookingRow)
class BookingRepository(Repository[BookingRow]):
    async def by_idempotency_key(self, tenant_id: str, key: str) -> BookingRow | None:
        return await self.find_one(
            BookingRow.tenant_id == tenant_id, BookingRow.idempotency_key == key
        )

    async def overlapping(
        self,
        tenant_id: str,
        resource_id: str,
        starts_at: datetime,
        ends_at: datetime,
        *,
        exclude_booking_id: str | None = None,
    ) -> BookingRow | None:
        filters = [
            BookingRow.tenant_id == tenant_id,
            BookingRow.resource_id == resource_id,
            BookingRow.status.in_(("booked", "checked_in")),
            BookingRow.starts_at < ends_at,
            BookingRow.ends_at > starts_at,
        ]
        if exclude_booking_id is not None:
            filters.append(BookingRow.id != exclude_booking_id)
        return await self.find_one(*filters)

    async def tenant_booking(
        self, tenant_id: str, booking_id: str, *, for_update: bool = False
    ) -> BookingRow | None:
        return await self.find_one(
            BookingRow.tenant_id == tenant_id,
            BookingRow.id == booking_id,
            with_for_update=for_update,
        )


@repository(BookingOperationRow)
class BookingOperationRepository(Repository[BookingOperationRow]):
    async def by_idempotency_key(
        self, tenant_id: str, key: str
    ) -> BookingOperationRow | None:
        return await self.find_one(
            BookingOperationRow.tenant_id == tenant_id,
            BookingOperationRow.idempotency_key == key,
        )


@repository(BookingSeriesRow)
class BookingSeriesRepository(Repository[BookingSeriesRow]):
    async def by_idempotency_key(
        self, tenant_id: str, key: str
    ) -> BookingSeriesRow | None:
        return await self.find_one(
            BookingSeriesRow.tenant_id == tenant_id,
            BookingSeriesRow.idempotency_key == key,
        )


@repository(BookingCancellationOperationRow)
class BookingCancellationOperationRepository(
    Repository[BookingCancellationOperationRow]
):
    async def by_idempotency_key(
        self, tenant_id: str, key: str
    ) -> BookingCancellationOperationRow | None:
        return await self.find_one(
            BookingCancellationOperationRow.tenant_id == tenant_id,
            BookingCancellationOperationRow.idempotency_key == key,
        )


@repository(OutboxRow)
class OutboxRepository(Repository[OutboxRow]):
    async def claim_pending(
        self, claim_token: str, now: datetime, claimed_until: datetime
    ) -> OutboxRow | None:
        eligibility = (
            OutboxRow.published_at.is_(None),
            OutboxRow.dead_lettered_at.is_(None),
            OutboxRow.next_attempt_at <= now,
            (OutboxRow.claimed_until.is_(None) | (OutboxRow.claimed_until <= now)),
        )
        candidate = (
            select(OutboxRow.event_id)
            .where(*eligibility)
            .order_by(OutboxRow.created_at)
            .limit(1)
            .scalar_subquery()
        )
        rows = await self._scalars(
            update(OutboxRow)
            .where(OutboxRow.event_id == candidate, *eligibility)
            .values(
                claim_token=claim_token,
                claimed_until=claimed_until,
                attempts=OutboxRow.attempts + 1,
            )
            .returning(OutboxRow)
            .execution_options(synchronize_session=False)
        )
        return rows.one_or_none()

    async def tenant_rows(self, tenant_id: str) -> list[OutboxRow]:
        return list(await self.find(OutboxRow.tenant_id == tenant_id))


@repository(AuditRow)
class AuditRepository(Repository[AuditRow]):
    pass


class IdempotencyConflict(Exception):
    pass


class BookingConflict(Exception):
    pass


class BookingStatusTransitionError(BookingConflict):
    pass


_LEGAL_TRANSITIONS = {
    "booked": ("checked_in", "cancelled", "no_show"),
    "checked_in": ("completed", "cancelled"),
    "cancelled": (),
    "no_show": (),
    "completed": (),
}


@dataclass(frozen=True, slots=True)
class CreateBookingCommand(Command[Booking]):
    tenant_id: str
    actor_id: str
    resource_id: str
    starts_at: datetime
    ends_at: datetime
    idempotency_key: str
    resource_active: bool = True
    office_policy: OfficePolicy | None = None


@dataclass(frozen=True, slots=True)
class RescheduleBookingCommand(Command[Booking]):
    tenant_id: str
    actor_id: str
    roles: tuple[str, ...]
    booking_id: str
    starts_at: datetime
    ends_at: datetime
    idempotency_key: str
    resource_active: bool = True
    office_policy: OfficePolicy | None = None


@dataclass(frozen=True, slots=True)
class CreateRecurringBookingCommand(Command[list[Booking]]):
    tenant_id: str
    actor_id: str
    resource_id: str
    starts_at: datetime
    ends_at: datetime
    recurrence: str
    occurrence_count: int
    idempotency_key: str
    resource_active: bool = True
    office_policy: OfficePolicy | None = None


@dataclass(frozen=True, slots=True)
class GetBookingQuery(Query[Booking]):
    tenant_id: str
    actor_id: str
    roles: tuple[str, ...]
    booking_id: str


@dataclass(frozen=True, slots=True)
class ListBookingsQuery(Query[list[Booking]]):
    tenant_id: str
    actor_id: str
    roles: tuple[str, ...]
    resource_id: str | None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    offset: int = 0
    limit: int = 100


@dataclass(frozen=True, slots=True)
class AvailabilityQuery(Query[list[Availability]]):
    tenant_id: str
    starts_at: datetime
    ends_at: datetime
    resource_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FacilityDashboardQuery(Query[FacilityDashboard]):
    tenant_id: str


@dataclass(frozen=True, slots=True)
class SetBookingStatusCommand(Command[Booking]):
    tenant_id: str
    actor_id: str
    roles: tuple[str, ...]
    booking_id: str
    status: str


@dataclass(frozen=True, slots=True)
class CancelBookingCommand(Command[list[Booking]]):
    tenant_id: str
    actor_id: str
    roles: tuple[str, ...]
    booking_id: str
    scope: str
    idempotency_key: str


@command_handler(CreateBookingCommand)
class CreateBookingHandler:
    def __init__(
        self,
        entities: EntityManager,
        bookings: BookingRepository,
        outbox: OutboxRepository,
        audit: AuditRepository,
    ) -> None:
        self._entities, self._bookings, self._outbox, self._audit = (
            entities,
            bookings,
            outbox,
            audit,
        )

    async def handle(self, command: CreateBookingCommand) -> Booking:
        _validate(command)
        fingerprint = _fingerprint(command)
        try:
            async with self._entities.transaction():
                existing = await self._bookings.by_idempotency_key(
                    command.tenant_id, command.idempotency_key
                )
                if existing is not None:
                    return _idempotent_booking(existing, fingerprint)
                if not command.resource_active:
                    raise BookingConflict("resource is inactive")
                _validate_office_period(
                    command.starts_at, command.ends_at, command.office_policy
                )
                if await self._bookings.overlapping(
                    command.tenant_id,
                    command.resource_id,
                    command.starts_at,
                    command.ends_at,
                ):
                    raise BookingConflict("resource is already booked for this period")
                row = await self._bookings.add(
                    BookingRow(
                        id=str(uuid4()),
                        tenant_id=command.tenant_id,
                        actor_id=command.actor_id,
                        resource_id=command.resource_id,
                        starts_at=command.starts_at,
                        ends_at=command.ends_at,
                        status="booked",
                        idempotency_key=command.idempotency_key,
                        request_fingerprint=fingerprint,
                    )
                )
                booking = _booking(row)
                event = BookingCreated(
                    booking.tenant_id,
                    booking.id,
                    booking.actor_id,
                    booking.resource_id,
                )
                await self._outbox.add(
                    OutboxRow(
                        event_id=str(uuid4()),
                        event_name="booking-created",
                        tenant_id=booking.tenant_id,
                        payload=json.dumps(
                            {
                                "tenant_id": event.tenant_id,
                                "booking_id": event.booking_id,
                                "actor_id": event.actor_id,
                                "resource_id": event.resource_id,
                            },
                            separators=(",", ":"),
                        ),
                    )
                )
                await self._audit.add(
                    _audit_row(
                        booking, command.actor_id, "booking-created", None, "booked"
                    )
                )
                return booking
        except IntegrityError as error:
            if _sqlstate(error) == "23P01":
                raise BookingConflict(
                    "resource is already booked for this period"
                ) from error
            if not _is_idempotency_violation(error):
                raise
            async with self._entities.transaction():
                existing = await self._bookings.by_idempotency_key(
                    command.tenant_id, command.idempotency_key
                )
                if existing is None:
                    raise
                return _idempotent_booking(existing, fingerprint)


@command_handler(RescheduleBookingCommand)
class RescheduleBookingHandler:
    def __init__(
        self,
        entities: EntityManager,
        bookings: BookingRepository,
        operations: BookingOperationRepository,
        outbox: OutboxRepository,
        audit: AuditRepository,
    ) -> None:
        self._entities = entities
        self._bookings = bookings
        self._operations = operations
        self._outbox = outbox
        self._audit = audit

    async def handle(self, command: RescheduleBookingCommand) -> Booking:
        _validate(command)
        fingerprint = _reschedule_fingerprint(command)
        async with _booking_transaction(self._entities):
            operation = await self._operations.by_idempotency_key(
                command.tenant_id, command.idempotency_key
            )
            if operation is not None:
                if operation.request_fingerprint != fingerprint:
                    raise IdempotencyConflict(
                        "idempotency key belongs to a different request"
                    )
                row = await self._bookings.tenant_booking(
                    command.tenant_id, operation.booking_id
                )
                if row is None:
                    raise LookupError("booking was not found")
                return _booking_at(
                    row, operation.result_starts_at, operation.result_ends_at
                )

            row = await self._bookings.tenant_booking(
                command.tenant_id, command.booking_id, for_update=True
            )
            if row is None:
                raise LookupError("booking was not found")
            if (
                row.actor_id != command.actor_id
                and "facilities-admin" not in command.roles
            ):
                raise PermissionError("booking belongs to another employee")
            if row.status != "booked":
                raise BookingStatusTransitionError(
                    "only booked bookings can be rescheduled"
                )
            if not command.resource_active:
                raise BookingConflict("resource is inactive")
            _validate_office_period(
                command.starts_at, command.ends_at, command.office_policy
            )
            if await self._bookings.overlapping(
                command.tenant_id,
                row.resource_id,
                command.starts_at,
                command.ends_at,
                exclude_booking_id=row.id,
            ):
                raise BookingConflict("resource is already booked for this period")

            row.starts_at, row.ends_at = command.starts_at, command.ends_at
            booking = _booking(row)
            await self._operations.add(
                BookingOperationRow(
                    id=str(uuid4()),
                    tenant_id=command.tenant_id,
                    booking_id=row.id,
                    idempotency_key=command.idempotency_key,
                    request_fingerprint=fingerprint,
                    result_starts_at=booking.starts_at,
                    result_ends_at=booking.ends_at,
                )
            )
            await _write_rescheduled(
                self._outbox, self._audit, booking, command.actor_id
            )
            await self._entities.flush()
            return booking


@command_handler(CreateRecurringBookingCommand)
class CreateRecurringBookingHandler:
    def __init__(
        self,
        entities: EntityManager,
        bookings: BookingRepository,
        series: BookingSeriesRepository,
        outbox: OutboxRepository,
        audit: AuditRepository,
    ) -> None:
        self._entities = entities
        self._bookings = bookings
        self._series = series
        self._outbox = outbox
        self._audit = audit

    async def handle(self, command: CreateRecurringBookingCommand) -> list[Booking]:
        _validate(command)
        if command.recurrence not in ("daily", "weekly"):
            raise ValueError("recurrence must be daily or weekly")
        if not 2 <= command.occurrence_count <= 52:
            raise ValueError("occurrence count must be between 2 and 52")
        fingerprint = _recurring_fingerprint(command)
        try:
            return await self._materialize(command, fingerprint)
        except IntegrityError as error:
            if not _is_series_idempotency_violation(error):
                raise
            async with self._entities.transaction():
                existing = await self._series.by_idempotency_key(
                    command.tenant_id, command.idempotency_key
                )
                if existing is None:
                    raise
                return await self._replay(existing, fingerprint)

    async def _materialize(
        self, command: CreateRecurringBookingCommand, fingerprint: str
    ) -> list[Booking]:
        async with _booking_transaction(self._entities):
            existing = await self._series.by_idempotency_key(
                command.tenant_id, command.idempotency_key
            )
            if existing is not None:
                return await self._replay(existing, fingerprint)
            if not command.resource_active:
                raise BookingConflict("resource is inactive")

            periods = _recurring_periods(command)
            for starts_at, ends_at in periods:
                _validate_office_period(starts_at, ends_at, command.office_policy)
            for starts_at, ends_at in periods:
                if await self._bookings.overlapping(
                    command.tenant_id, command.resource_id, starts_at, ends_at
                ):
                    raise BookingConflict("resource is already booked for this period")

            series = await self._series.add(
                BookingSeriesRow(
                    id=str(uuid4()),
                    tenant_id=command.tenant_id,
                    idempotency_key=command.idempotency_key,
                    request_fingerprint=fingerprint,
                )
            )
            occurrences: list[Booking] = []
            for index, (starts_at, ends_at) in enumerate(periods):
                row = await self._bookings.add(
                    BookingRow(
                        id=str(uuid4()),
                        tenant_id=command.tenant_id,
                        actor_id=command.actor_id,
                        resource_id=command.resource_id,
                        starts_at=starts_at,
                        ends_at=ends_at,
                        status="booked",
                        idempotency_key=f"{series.id}:{index}",
                        request_fingerprint=fingerprint,
                        series_id=series.id,
                        occurrence_index=index,
                    )
                )
                booking = _booking(row)
                await _write_created(
                    self._outbox, self._audit, booking, command.actor_id
                )
                occurrences.append(booking)
            return occurrences

    async def _replay(
        self, series: BookingSeriesRow, fingerprint: str
    ) -> list[Booking]:
        if series.request_fingerprint != fingerprint:
            raise IdempotencyConflict("idempotency key belongs to a different request")
        rows = await self._bookings.find(
            BookingRow.tenant_id == series.tenant_id,
            BookingRow.series_id == series.id,
            order_by=(BookingRow.occurrence_index,),
        )
        return [_booking(row) for row in rows]


@query_handler(GetBookingQuery)
class GetBookingHandler:
    def __init__(self, bookings: BookingRepository) -> None:
        self._bookings = bookings

    async def handle(self, query: GetBookingQuery) -> Booking:
        row = await self._bookings.tenant_booking(query.tenant_id, query.booking_id)
        if row is None or (
            row.actor_id != query.actor_id and "facilities-admin" not in query.roles
        ):
            raise LookupError("booking was not found")
        return _booking(row)


@query_handler(ListBookingsQuery)
class ListBookingsHandler:
    def __init__(self, bookings: BookingRepository) -> None:
        self._bookings = bookings

    async def handle(self, query: ListBookingsQuery) -> list[Booking]:
        filters = [BookingRow.tenant_id == query.tenant_id]
        if "facilities-admin" not in query.roles:
            filters.append(BookingRow.actor_id == query.actor_id)
        if query.resource_id:
            filters.append(BookingRow.resource_id == query.resource_id)
        if query.starts_at:
            filters.append(BookingRow.ends_at > query.starts_at)
        if query.ends_at:
            filters.append(BookingRow.starts_at < query.ends_at)
        rows = await self._bookings.find(
            *filters,
            order_by=(BookingRow.starts_at.desc(), BookingRow.id),
            offset=query.offset,
            limit=query.limit,
        )
        return [_booking(row) for row in rows]


@query_handler(AvailabilityQuery)
class AvailabilityHandler:
    def __init__(self, bookings: BookingRepository) -> None:
        self._bookings = bookings

    async def handle(self, query: AvailabilityQuery) -> list[Availability]:
        filters = [
            BookingRow.tenant_id == query.tenant_id,
            BookingRow.status.in_(("booked", "checked_in")),
            BookingRow.starts_at < query.ends_at,
            BookingRow.ends_at > query.starts_at,
        ]
        if not query.resource_ids:
            return []
        filters.append(BookingRow.resource_id.in_(query.resource_ids))
        conflicts: dict[str, list[str]] = {
            resource_id: [] for resource_id in query.resource_ids
        }
        for row in await self._bookings.find(*filters):
            conflicts[row.resource_id].append(row.id)
        return [
            Availability(resource_id, not booking_ids, tuple(booking_ids))
            for resource_id, booking_ids in conflicts.items()
        ]


@query_handler(FacilityDashboardQuery)
class FacilitiesDashboardHandler:
    def __init__(self, bookings: BookingRepository, outbox: OutboxRepository) -> None:
        self._bookings, self._outbox = bookings, outbox

    async def handle(self, query: FacilityDashboardQuery) -> FacilityDashboard:
        rows = await self._bookings.find(BookingRow.tenant_id == query.tenant_id)
        outbox = await self._outbox.tenant_rows(query.tenant_id)
        pending = [
            row
            for row in outbox
            if row.published_at is None and row.dead_lettered_at is None
        ]
        eligible = [row for row in pending if _as_utc(row.next_attempt_at) <= utc_now()]
        return FacilityDashboard(
            active_bookings=sum(row.status in ("booked", "checked_in") for row in rows),
            no_shows=sum(row.status == "no_show" for row in rows),
            outbox_pending=len(pending),
            outbox_dead_letter=sum(row.dead_lettered_at is not None for row in outbox),
            outbox_failures=sum(
                row.attempts > 0 and row.published_at is None for row in outbox
            ),
            outbox_lag_seconds=_outbox_lag_seconds(eligible),
        )


@command_handler(SetBookingStatusCommand)
class SetBookingStatusHandler:
    def __init__(
        self,
        entities: EntityManager,
        bookings: BookingRepository,
        outbox: OutboxRepository,
        audit: AuditRepository,
    ) -> None:
        self._entities, self._bookings, self._outbox, self._audit = (
            entities,
            bookings,
            outbox,
            audit,
        )

    async def handle(self, command: SetBookingStatusCommand) -> Booking:
        async with self._entities.transaction():
            row = await self._bookings.tenant_booking(
                command.tenant_id, command.booking_id, for_update=True
            )
            if row is None:
                raise LookupError("booking was not found")
            if (
                row.actor_id != command.actor_id
                and "facilities-admin" not in command.roles
            ):
                raise PermissionError("booking belongs to another employee")
            if command.status == row.status:
                return _booking(row)
            if command.status not in _LEGAL_TRANSITIONS.get(row.status, ()):
                raise BookingStatusTransitionError(
                    f"cannot transition booking from {row.status} to {command.status}"
                )
            before = row.status
            row.status = command.status
            booking = _booking(row)
            await _write_lifecycle(
                self._outbox, self._audit, booking, command.actor_id, before
            )
            await self._entities.flush()
            return booking


@command_handler(CancelBookingCommand)
class CancelBookingHandler:
    def __init__(
        self,
        entities: EntityManager,
        bookings: BookingRepository,
        operations: BookingCancellationOperationRepository,
        outbox: OutboxRepository,
        audit: AuditRepository,
    ) -> None:
        self._entities = entities
        self._bookings = bookings
        self._operations = operations
        self._outbox = outbox
        self._audit = audit

    async def handle(self, command: CancelBookingCommand) -> list[Booking]:
        if command.scope not in ("one", "this-and-following", "entire-series"):
            raise ValueError("cancellation scope is invalid")
        fingerprint = _cancellation_fingerprint(command)
        try:
            return await self._cancel(command, fingerprint)
        except IntegrityError as error:
            if not _is_cancellation_idempotency_violation(error):
                raise
            async with self._entities.transaction():
                operation = await self._operations.by_idempotency_key(
                    command.tenant_id, command.idempotency_key
                )
                if operation is None:
                    raise
                return await self._replay(operation, fingerprint)

    async def _cancel(
        self, command: CancelBookingCommand, fingerprint: str
    ) -> list[Booking]:
        async with self._entities.transaction():
            operation = await self._operations.by_idempotency_key(
                command.tenant_id, command.idempotency_key
            )
            if operation is not None:
                return await self._replay(operation, fingerprint)

            target = await self._bookings.tenant_booking(
                command.tenant_id,
                command.booking_id,
                for_update=command.scope == "one",
            )
            if target is None:
                raise LookupError("booking was not found")
            if (
                target.actor_id != command.actor_id
                and "facilities-admin" not in command.roles
            ):
                raise PermissionError("booking belongs to another employee")
            if command.scope != "one" and target.series_id is None:
                raise ValueError("series cancellation requires a recurring booking")

            rows = await self._rows_for_scope(command, target)
            result: list[Booking] = []
            for row in rows:
                if (
                    row.actor_id != command.actor_id
                    and "facilities-admin" not in command.roles
                ):
                    raise PermissionError("booking belongs to another employee")
                if row.status == "cancelled":
                    result.append(_booking(row))
                    continue
                if "cancelled" not in _LEGAL_TRANSITIONS.get(row.status, ()):
                    continue
                before = row.status
                row.status = "cancelled"
                booking = _booking(row)
                await _write_lifecycle(
                    self._outbox, self._audit, booking, command.actor_id, before
                )
                result.append(booking)

            await self._operations.add(
                BookingCancellationOperationRow(
                    id=str(uuid4()),
                    tenant_id=command.tenant_id,
                    idempotency_key=command.idempotency_key,
                    request_fingerprint=fingerprint,
                    result_booking_ids_json=json.dumps(
                        [booking.id for booking in result], separators=(",", ":")
                    ),
                )
            )
            await self._entities.flush()
            return result

    async def _rows_for_scope(
        self, command: CancelBookingCommand, target: BookingRow
    ) -> list[BookingRow]:
        if command.scope == "one":
            return [target]
        if target.occurrence_index is None:
            raise ValueError("series occurrence metadata is invalid")
        filters = [
            BookingRow.tenant_id == command.tenant_id,
            BookingRow.series_id == target.series_id,
        ]
        if command.scope == "this-and-following":
            filters.append(BookingRow.occurrence_index >= target.occurrence_index)
        rows = (
            await self._entities.scalars(
                select(BookingRow)
                .where(*filters)
                .order_by(BookingRow.occurrence_index)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
        return list(rows)

    async def _replay(
        self, operation: BookingCancellationOperationRow, fingerprint: str
    ) -> list[Booking]:
        if operation.request_fingerprint != fingerprint:
            raise IdempotencyConflict("idempotency key belongs to a different request")
        result: list[Booking] = []
        for booking_id in json.loads(operation.result_booking_ids_json):
            row = await self._bookings.tenant_booking(operation.tenant_id, booking_id)
            if row is None:
                raise LookupError("booking was not found")
            result.append(_booking(row))
        return result


@injectable()
class BookingExpiryService:
    """Deterministic lifecycle expiry; callers provide the clock."""

    def __init__(
        self,
        entities: EntityManager,
        bookings: BookingRepository,
        outbox: OutboxRepository,
        audit: AuditRepository,
        poll_interval: float = 30,
    ) -> None:
        self._entities, self._bookings, self._outbox, self._audit = (
            entities,
            bookings,
            outbox,
            audit,
        )
        self._poll_interval = poll_interval
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def on_application_bootstrap(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def on_application_shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                await self.expire(utc_now())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("booking expiry failed")
            await asyncio.sleep(self._poll_interval)

    async def expire(self, now: datetime) -> list[Booking]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("expiry time must be timezone-aware")
        async with self._lock:
            return await self._expire(now)

    async def _expire(self, now: datetime) -> list[Booking]:
        changed: list[Booking] = []
        async with self._entities.transaction():
            rows = (
                await self._entities.scalars(
                    select(BookingRow)
                    .where(BookingRow.status.in_(("booked", "checked_in")))
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                status = (
                    "no_show"
                    if row.status == "booked"
                    and _as_utc(row.starts_at) + timedelta(minutes=15) < now
                    else "completed"
                    if row.status == "checked_in" and _as_utc(row.ends_at) < now
                    else None
                )
                if status is None:
                    continue
                previous = row.status
                row.status = status
                booking = _booking(row)
                await _write_lifecycle(
                    self._outbox, self._audit, booking, "system", previous
                )
                changed.append(booking)
            await self._entities.flush()
        return changed


async def _write_lifecycle(
    outbox: OutboxRepository,
    audit: AuditRepository,
    booking: Booking,
    actor_id: str,
    previous: str,
) -> None:
    event_name = f"booking-{booking.status.replace('_', '-')}"
    event = BookingLifecycleEvent(
        booking.tenant_id,
        booking.id,
        booking.actor_id,
        booking.resource_id,
        cast(
            Literal["cancelled", "checked_in", "no_show", "completed"], booking.status
        ),
    )
    await outbox.add(
        OutboxRow(
            event_id=str(uuid4()),
            event_name=event_name,
            tenant_id=booking.tenant_id,
            payload=json.dumps(
                {
                    "tenant_id": event.tenant_id,
                    "booking_id": event.booking_id,
                    "actor_id": event.actor_id,
                    "resource_id": event.resource_id,
                    "status": event.status,
                },
                separators=(",", ":"),
            ),
        )
    )
    await audit.add(_audit_row(booking, actor_id, event_name, previous, booking.status))


async def _write_created(
    outbox: OutboxRepository,
    audit: AuditRepository,
    booking: Booking,
    actor_id: str,
) -> None:
    event = BookingCreated(
        booking.tenant_id, booking.id, booking.actor_id, booking.resource_id
    )
    await outbox.add(
        OutboxRow(
            event_id=str(uuid4()),
            event_name="booking-created",
            tenant_id=booking.tenant_id,
            payload=json.dumps(
                {
                    "tenant_id": event.tenant_id,
                    "booking_id": event.booking_id,
                    "actor_id": event.actor_id,
                    "resource_id": event.resource_id,
                },
                separators=(",", ":"),
            ),
        )
    )
    await audit.add(_audit_row(booking, actor_id, "booking-created", None, "booked"))


async def _write_rescheduled(
    outbox: OutboxRepository,
    audit: AuditRepository,
    booking: Booking,
    actor_id: str,
) -> None:
    event = BookingRescheduled(
        booking.tenant_id,
        booking.id,
        booking.actor_id,
        booking.resource_id,
        booking.starts_at,
        booking.ends_at,
    )
    await outbox.add(
        OutboxRow(
            event_id=str(uuid4()),
            event_name="booking-rescheduled",
            tenant_id=booking.tenant_id,
            payload=json.dumps(
                {
                    "tenant_id": event.tenant_id,
                    "booking_id": event.booking_id,
                    "actor_id": event.actor_id,
                    "resource_id": event.resource_id,
                    "starts_at": event.starts_at.isoformat(),
                    "ends_at": event.ends_at.isoformat(),
                },
                separators=(",", ":"),
            ),
        )
    )
    await audit.add(
        _audit_row(booking, actor_id, "booking-rescheduled", "booked", "booked")
    )


def _audit_row(
    booking: Booking,
    actor_id: str,
    action: str,
    from_status: str | None,
    to_status: str,
) -> AuditRow:
    return AuditRow(
        id=str(uuid4()),
        tenant_id=booking.tenant_id,
        booking_id=booking.id,
        resource_id=booking.resource_id,
        actor_id=actor_id,
        action=action,
        from_status=from_status,
        to_status=to_status,
        created_at=datetime.now(UTC),
    )


@injectable()
class OutboxRelay:
    """Publishes at least once; consumers deduplicate event IDs."""

    def __init__(
        self, entities: EntityManager, outbox: OutboxRepository, events: EventDispatcher
    ) -> None:
        self._entities, self._outbox, self._events = entities, outbox, events
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
        claim_token = str(uuid4())
        now = utc_now()
        async with self._entities.transaction():
            row = await self._outbox.claim_pending(
                claim_token, now, now + OUTBOX_CLAIM_LEASE
            )
            if row is None:
                return False
            event_id, event_name = row.event_id, row.event_name
            payload = json.loads(row.payload)
        try:
            await self._events.publish(
                event_name,
                1,
                payload,
                headers={"outbox_event_id": event_id},
                require_route=True,
            )
        except Exception as error:
            async with self._entities.transaction():
                failed = await self._outbox.find_one(
                    OutboxRow.event_id == event_id,
                    OutboxRow.claim_token == claim_token,
                    OutboxRow.published_at.is_(None),
                    with_for_update=True,
                )
                if failed is not None:
                    failed.last_error = str(error)[:4096]
                    failed.claim_token = None
                    failed.claimed_until = None
                    if failed.attempts >= 5:
                        failed.dead_lettered_at = utc_now()
                    else:
                        failed.next_attempt_at = utc_now() + timedelta(
                            seconds=min(60, 2 ** (failed.attempts - 1))
                        )
                    await self._entities.flush()
            raise
        async with self._entities.transaction():
            published = await self._outbox.find_one(
                OutboxRow.event_id == event_id,
                OutboxRow.claim_token == claim_token,
                OutboxRow.published_at.is_(None),
                with_for_update=True,
            )
            if published is not None:
                published.published_at = utc_now()
                published.claim_token = None
                published.claimed_until = None
                await self._entities.flush()
        return True


@controller()
class BookingsController:
    def __init__(
        self,
        commands: CommandBus,
        queries: QueryBus,
        entities: EntityManager,
        spaces: SpacesService,
        audit: AuditRepository,
        outbox: OutboxRepository,
    ) -> None:
        self._commands, self._queries = commands, queries
        self._entities, self._spaces, self._audit, self._outbox = (
            entities,
            spaces,
            audit,
            outbox,
        )

    @rpc(BookingsService.create_booking)
    async def create_booking(
        self, payload: Annotated[CreateBooking, Payload()]
    ) -> Booking:
        _require_workplace_role(payload.principal)
        try:
            resource = await self._spaces.get_resource(
                payload.principal, payload.resource_id
            )
            policy = (
                await self._spaces.get_office_policy(
                    payload.principal, resource.office_id
                )
                if resource.active
                else None
            )
            return await self._commands.execute(
                CreateBookingCommand(
                    payload.principal.tenant_id,
                    payload.principal.actor_id,
                    payload.resource_id,
                    payload.starts_at,
                    payload.ends_at,
                    payload.idempotency_key,
                    resource.active,
                    policy,
                )
            )
        except (ValueError, IdempotencyConflict, BookingConflict) as error:
            raise PublicRpcError(
                "conflict" if not isinstance(error, ValueError) else "invalid_request",
                str(error),
            ) from error

    @rpc(BookingsService.create_recurring_booking)
    async def create_recurring_booking(
        self, payload: Annotated[CreateRecurringBooking, Payload()]
    ) -> list[Booking]:
        _require_workplace_role(payload.principal)
        try:
            resource = await self._spaces.get_resource(
                payload.principal, payload.resource_id
            )
            policy = (
                await self._spaces.get_office_policy(
                    payload.principal, resource.office_id
                )
                if resource.active
                else None
            )
            return await self._commands.execute(
                CreateRecurringBookingCommand(
                    payload.principal.tenant_id,
                    payload.principal.actor_id,
                    payload.resource_id,
                    payload.starts_at,
                    payload.ends_at,
                    payload.recurrence,
                    payload.occurrence_count,
                    payload.idempotency_key,
                    resource.active,
                    policy,
                )
            )
        except (ValueError, IdempotencyConflict, BookingConflict) as error:
            raise PublicRpcError(
                "conflict" if not isinstance(error, ValueError) else "invalid_request",
                str(error),
            ) from error

    @rpc(BookingsService.reschedule_booking)
    async def reschedule_booking(
        self, payload: Annotated[RescheduleBooking, Payload()]
    ) -> Booking:
        _require_workplace_role(payload.principal)
        try:
            booking = await self._get(GetBooking(payload.principal, payload.booking_id))
            resource = await self._spaces.get_resource(
                payload.principal, booking.resource_id
            )
            policy = (
                await self._spaces.get_office_policy(
                    payload.principal, resource.office_id
                )
                if resource.active
                else None
            )
            return await self._commands.execute(
                RescheduleBookingCommand(
                    payload.principal.tenant_id,
                    payload.principal.actor_id,
                    payload.principal.roles,
                    payload.booking_id,
                    payload.starts_at,
                    payload.ends_at,
                    payload.idempotency_key,
                    resource.active,
                    policy,
                )
            )
        except LookupError as error:
            raise PublicRpcError("not_found", "Booking was not found.") from error
        except PermissionError as error:
            raise PublicRpcError("forbidden", str(error)) from error
        except (ValueError, IdempotencyConflict, BookingConflict) as error:
            raise PublicRpcError(
                "conflict" if not isinstance(error, ValueError) else "invalid_request",
                str(error),
            ) from error

    @rpc(BookingsService.get_booking)
    async def get_booking(self, payload: Annotated[GetBooking, Payload()]) -> Booking:
        return await self._get(payload)

    async def _get(self, payload: GetBooking) -> Booking:
        _require_workplace_role(payload.principal)
        try:
            return await self._queries.execute(
                GetBookingQuery(
                    payload.principal.tenant_id,
                    payload.principal.actor_id,
                    payload.principal.roles,
                    payload.booking_id,
                )
            )
        except LookupError as error:
            raise PublicRpcError("not_found", "Booking was not found.") from error

    @rpc(BookingsService.list_bookings)
    async def list_bookings(
        self, payload: Annotated[ListBookings, Payload()]
    ) -> list[Booking]:
        _require_workplace_role(payload.principal)
        return await self._queries.execute(
            ListBookingsQuery(
                payload.principal.tenant_id,
                payload.principal.actor_id,
                payload.principal.roles,
                payload.resource_id,
                payload.starts_at,
                payload.ends_at,
                payload.offset,
                payload.limit,
            )
        )

    @rpc(BookingsService.availability)
    async def availability(
        self, payload: Annotated[AvailabilityPayload, Payload()]
    ) -> list[Availability]:
        _require_workplace_role(payload.principal)
        try:
            _validate_utc_interval(payload.starts_at, payload.ends_at)
        except ValueError as error:
            raise PublicRpcError("invalid_request", str(error)) from error
        if payload.resource_id:
            resource = await self._spaces.get_resource(
                payload.principal, payload.resource_id
            )
            if not resource.active:
                return [Availability(resource.id, False, ())]
            resources = [resource]
        elif payload.resource_ids:
            if len(payload.resource_ids) > 100:
                raise PublicRpcError(
                    "invalid_request", "Resource batch exceeds the supported size."
                )
            resources = await self._spaces.get_resources(
                payload.principal, payload.resource_ids
            )
        else:
            resources = []
            page_size = 100
            offset = 0
            while True:
                page = await self._spaces.list_resources(
                    payload.principal, offset=offset, limit=page_size
                )
                resources.extend(page)
                if len(page) < page_size:
                    break
                offset += page_size
        policies: dict[str, OfficePolicy] = {}
        closed_resource_ids: set[str] = set()
        for resource in resources:
            if not resource.active:
                closed_resource_ids.add(resource.id)
                continue
            policy = policies.get(resource.office_id)
            if policy is None:
                policy = await self._spaces.get_office_policy(
                    payload.principal, resource.office_id
                )
                policies[resource.office_id] = policy
            try:
                _validate_office_period(payload.starts_at, payload.ends_at, policy)
            except ValueError:
                closed_resource_ids.add(resource.id)
        availability = await self._queries.execute(
            AvailabilityQuery(
                payload.principal.tenant_id,
                payload.starts_at,
                payload.ends_at,
                tuple(resource.id for resource in resources),
            )
        )
        return [
            Availability(item.resource_id, False, ())
            if item.resource_id in closed_resource_ids
            else item
            for item in availability
        ]

    @rpc(BookingsService.facilities_dashboard)
    async def facilities_dashboard(
        self, payload: Annotated[AdminRequest, Payload()]
    ) -> FacilityDashboard:
        _require_admin_rpc(payload.principal)
        return await self._queries.execute(
            FacilityDashboardQuery(payload.principal.tenant_id)
        )

    @rpc(BookingsService.list_audit)
    async def list_audit(
        self, payload: Annotated[ListAudit, Payload()]
    ) -> list[AuditEntry]:
        _require_admin_rpc(payload.principal)
        filters = [AuditRow.tenant_id == payload.principal.tenant_id]
        if payload.starts_at:
            filters.append(AuditRow.created_at >= payload.starts_at)
        if payload.ends_at:
            filters.append(AuditRow.created_at < payload.ends_at)
        if payload.resource_id:
            filters.append(AuditRow.resource_id == payload.resource_id)
        rows = await self._audit.find(
            *filters, order_by=(AuditRow.created_at.desc(),), limit=payload.limit
        )
        return [
            AuditEntry(
                row.id,
                row.tenant_id,
                row.booking_id,
                row.resource_id,
                row.actor_id,
                row.action,
                row.from_status,
                row.to_status,
                _as_utc(row.created_at),
            )
            for row in rows
        ]

    @rpc(BookingsService.outbox_diagnostics)
    async def outbox_diagnostics(
        self, payload: Annotated[AdminRequest, Payload()]
    ) -> OutboxDiagnostics:
        _require_admin_rpc(payload.principal)
        return _outbox_diagnostics(
            await self._outbox.tenant_rows(payload.principal.tenant_id)
        )

    @rpc(BookingsService.cleanup_outbox)
    async def cleanup_outbox(self, payload: Annotated[CleanupOutbox, Payload()]) -> int:
        _require_admin_rpc(payload.principal)
        try:
            _validate_utc(payload.before)
        except ValueError as error:
            raise PublicRpcError("invalid_request", str(error)) from error
        async with self._entities.transaction():
            result = await self._entities.execute(
                delete(OutboxRow).where(
                    OutboxRow.tenant_id == payload.principal.tenant_id,
                    OutboxRow.published_at.is_not(None),
                    OutboxRow.published_at < payload.before,
                )
            )
            return int(getattr(result, "rowcount", 0) or 0)

    async def _set(self, payload: GetBooking, status: str) -> Booking:
        _require_workplace_role(payload.principal)
        try:
            return await self._commands.execute(
                SetBookingStatusCommand(
                    payload.principal.tenant_id,
                    payload.principal.actor_id,
                    payload.principal.roles,
                    payload.booking_id,
                    status,
                )
            )
        except LookupError as error:
            raise PublicRpcError("not_found", "Booking was not found.") from error
        except PermissionError as error:
            raise PublicRpcError("forbidden", str(error)) from error
        except BookingConflict as error:
            raise PublicRpcError("conflict", str(error)) from error

    @rpc(BookingsService.cancel_booking)
    async def cancel_booking(
        self, payload: Annotated[CancelBooking, Payload()]
    ) -> list[Booking]:
        _require_workplace_role(payload.principal)
        try:
            return await self._commands.execute(
                CancelBookingCommand(
                    payload.principal.tenant_id,
                    payload.principal.actor_id,
                    payload.principal.roles,
                    payload.booking_id,
                    payload.scope,
                    payload.idempotency_key,
                )
            )
        except LookupError as error:
            raise PublicRpcError("not_found", "Booking was not found.") from error
        except PermissionError as error:
            raise PublicRpcError("forbidden", str(error)) from error
        except (ValueError, IdempotencyConflict, BookingConflict) as error:
            raise PublicRpcError(
                "conflict" if not isinstance(error, ValueError) else "invalid_request",
                str(error),
            ) from error

    @rpc(BookingsService.check_in_booking)
    async def check_in_booking(
        self, payload: Annotated[CheckInBooking, Payload()]
    ) -> Booking:
        return await self._set(payload, "checked_in")

    @rpc(BookingsService.health)
    async def health(self, payload: Annotated[Health, Payload()]) -> dict[str, str]:
        del payload
        await self._entities.scalar(select(1))
        return {"status": "ok"}


bookings_sql = sql_module("bookings")
bookings_feature = SqlAlchemyModule.for_feature(
    [
        BookingRepository,
        BookingOperationRepository,
        BookingSeriesRepository,
        BookingCancellationOperationRepository,
        OutboxRepository,
        AuditRepository,
    ]
)
bookings_reference, bookings_rabbit, bookings_service = rabbit_modules(BOOKINGS)
bookings_clients = ClientsModule.register_cluster(
    bookings_reference,
    imports=(bookings_rabbit,),
    contracts=(SpacesService,),
)
cqrs = CqrsModule.for_root(global_=True)


@module(
    imports=(bookings_sql, bookings_feature, cqrs, bookings_service, bookings_clients),
    providers=(
        CreateBookingHandler,
        RescheduleBookingHandler,
        CreateRecurringBookingHandler,
        GetBookingHandler,
        ListBookingsHandler,
        AvailabilityHandler,
        FacilitiesDashboardHandler,
        SetBookingStatusHandler,
        CancelBookingHandler,
        BookingExpiryService,
        OutboxRelay,
    ),
    controllers=(BookingsController,),
)
class BookingsAppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(BookingsAppModule)


async def run() -> None:
    await serve(create_application)


@asynccontextmanager
async def _booking_transaction(entities: EntityManager) -> AsyncIterator[None]:
    """Keep Postgres exclusion races indistinguishable from preflight conflicts."""

    try:
        async with entities.transaction():
            yield
    except IntegrityError as error:
        if _sqlstate(error) == "23P01":
            raise BookingConflict(
                "resource is already booked for this period"
            ) from error
        raise


def _validate(
    command: CreateBookingCommand
    | RescheduleBookingCommand
    | CreateRecurringBookingCommand,
) -> None:
    _validate_utc_interval(command.starts_at, command.ends_at)
    if (
        command.starts_at >= command.ends_at
        or command.ends_at - command.starts_at > MAX_BOOKING_DURATION
    ):
        raise ValueError("booking period is invalid")


def _validate_utc_interval(starts_at: datetime, ends_at: datetime) -> None:
    _validate_utc(starts_at)
    _validate_utc(ends_at)
    if starts_at >= ends_at:
        raise ValueError("availability period is invalid")


def _validate_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be UTC")


def _outbox_lag_seconds(rows: list[OutboxRow]) -> float | None:
    if not rows:
        return None
    return max(
        0.0, (utc_now() - min(_as_utc(row.created_at) for row in rows)).total_seconds()
    )


def _outbox_diagnostics(rows: list[OutboxRow]) -> OutboxDiagnostics:
    pending = [
        row for row in rows if row.published_at is None and row.dead_lettered_at is None
    ]
    eligible = [row for row in pending if _as_utc(row.next_attempt_at) <= utc_now()]
    return OutboxDiagnostics(
        pending=len(pending),
        dead_letter=sum(row.dead_lettered_at is not None for row in rows),
        failures=sum(row.attempts > 0 and row.published_at is None for row in rows),
        lag_seconds=_outbox_lag_seconds(eligible),
    )


def _fingerprint(command: CreateBookingCommand) -> str:
    data = "|".join(
        (
            command.tenant_id,
            command.actor_id,
            command.resource_id,
            command.starts_at.astimezone(UTC).isoformat(),
            command.ends_at.astimezone(UTC).isoformat(),
        )
    )
    return sha256(data.encode()).hexdigest()


def _reschedule_fingerprint(command: RescheduleBookingCommand) -> str:
    return _hash_fields(
        command.tenant_id,
        command.actor_id,
        command.booking_id,
        command.starts_at.astimezone(UTC).isoformat(),
        command.ends_at.astimezone(UTC).isoformat(),
    )


def _recurring_fingerprint(command: CreateRecurringBookingCommand) -> str:
    return _hash_fields(
        command.tenant_id,
        command.actor_id,
        command.resource_id,
        command.starts_at.astimezone(UTC).isoformat(),
        command.ends_at.astimezone(UTC).isoformat(),
        command.recurrence,
        str(command.occurrence_count),
    )


def _cancellation_fingerprint(command: CancelBookingCommand) -> str:
    return _hash_fields(
        command.tenant_id,
        command.actor_id,
        command.booking_id,
        command.scope,
    )


def _hash_fields(*fields: str) -> str:
    return sha256("|".join(fields).encode()).hexdigest()


def _idempotent_booking(row: BookingRow, fingerprint: str) -> Booking:
    if row.request_fingerprint != fingerprint:
        raise IdempotencyConflict("idempotency key belongs to a different request")
    return _booking(row)


def _sqlstate(error: IntegrityError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


def _is_idempotency_violation(error: IntegrityError) -> bool:
    if _sqlstate(error) == "23505":
        return True
    return (
        "UNIQUE constraint failed: bookings.tenant_id, bookings.idempotency_key"
        in str(error.orig)
    )


def _is_series_idempotency_violation(error: IntegrityError) -> bool:
    constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint == "booking_series_tenant_id_idempotency_key_key":
        return True
    return (
        "UNIQUE constraint failed: booking_series.tenant_id, "
        "booking_series.idempotency_key" in str(error.orig)
    )


def _is_cancellation_idempotency_violation(error: IntegrityError) -> bool:
    constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint == "booking_cancellation_operations_tenant_id_idempotency_key_key":
        return True
    return (
        "UNIQUE constraint failed: booking_cancellation_operations.tenant_id, "
        "booking_cancellation_operations.idempotency_key" in str(error.orig)
    )


def _recurring_periods(
    command: CreateRecurringBookingCommand,
) -> list[tuple[datetime, datetime]]:
    step = timedelta(days=1 if command.recurrence == "daily" else 7)
    if command.office_policy is None:
        return [
            (command.starts_at + step * index, command.ends_at + step * index)
            for index in range(command.occurrence_count)
        ]
    zone = ZoneInfo(command.office_policy.time_zone)
    local_start = command.starts_at.astimezone(zone)
    local_end = command.ends_at.astimezone(zone)
    return [
        (
            _strict_local(local_start.replace(tzinfo=None) + step * index, zone),
            _strict_local(local_end.replace(tzinfo=None) + step * index, zone),
        )
        for index in range(command.occurrence_count)
    ]


def _strict_local(value: datetime, zone: ZoneInfo) -> datetime:
    candidates = [value.replace(tzinfo=zone, fold=fold) for fold in (0, 1)]
    valid = [
        candidate
        for candidate in candidates
        if candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == value
    ]
    offsets = {candidate.utcoffset() for candidate in valid}
    if not valid or len(offsets) != 1:
        raise ValueError(
            "recurring booking crosses an ambiguous or nonexistent office time"
        )
    return valid[0].astimezone(UTC)


def _validate_office_period(
    starts_at: datetime, ends_at: datetime, policy: OfficePolicy | None
) -> None:
    if policy is None:
        return
    zone = ZoneInfo(policy.time_zone)
    local_start = starts_at.astimezone(zone)
    local_end = ends_at.astimezone(zone)
    opens_at = _policy_time(policy.opens_at)
    closes_at = _policy_time(policy.closes_at)
    starts_time = local_start.timetz().replace(tzinfo=None)
    ends_time = local_end.timetz().replace(tzinfo=None)
    if (
        local_start.date() != local_end.date()
        or local_start.weekday() not in policy.weekdays
        or starts_time < opens_at
        or ends_time > closes_at
    ):
        raise ValueError("booking must be within office hours")


def _policy_time(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour, minute)


def _require_workplace_role(principal: Principal) -> None:
    if not has_workplace_role(principal):
        raise PublicRpcError("forbidden", "A workplace role is required.")


def _require_admin_rpc(principal: Principal) -> None:
    if not is_facilities_admin(principal):
        raise PublicRpcError("forbidden", "Facilities administrator role is required.")


def _booking(row: BookingRow) -> Booking:
    return Booking(
        row.id,
        row.tenant_id,
        row.actor_id,
        row.resource_id,
        _as_utc(row.starts_at),
        _as_utc(row.ends_at),
        row.status,
        row.idempotency_key,
        row.series_id,
        row.occurrence_index,
    )


def _booking_at(row: BookingRow, starts_at: datetime, ends_at: datetime) -> Booking:
    booking = _booking(row)
    return Booking(
        booking.id,
        booking.tenant_id,
        booking.actor_id,
        booking.resource_id,
        _as_utc(starts_at),
        _as_utc(ends_at),
        booking.status,
        booking.idempotency_key,
        booking.series_id,
        booking.occurrence_index,
    )


def _as_utc(value: datetime) -> datetime:
    """SQLite does not round-trip timezone offsets despite timezone=True."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


if __name__ == "__main__":
    asyncio.run(run())
