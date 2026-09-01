"""Tenant-isolated booking service with explicit idempotency semantics."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Literal, cast
from uuid import uuid4

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
    CancelBooking,
    CheckInBooking,
    CleanupOutbox,
    CreateBooking,
    FacilityDashboard,
    GetBooking,
    Health,
    ListAudit,
    ListBookings,
    OutboxDiagnostics,
    Principal,
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


class BookingRow(Base):
    __tablename__ = "bookings"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128))
    resource_id: Mapped[str] = mapped_column(String(128), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="booked")
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))


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
        self, tenant_id: str, resource_id: str, starts_at: datetime, ends_at: datetime
    ) -> BookingRow | None:
        return await self.find_one(
            BookingRow.tenant_id == tenant_id,
            BookingRow.resource_id == resource_id,
            BookingRow.status.in_(("booked", "checked_in")),
            BookingRow.starts_at < ends_at,
            BookingRow.ends_at > starts_at,
        )

    async def tenant_booking(
        self, tenant_id: str, booking_id: str
    ) -> BookingRow | None:
        return await self.find_one(
            BookingRow.tenant_id == tenant_id, BookingRow.id == booking_id
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
                command.tenant_id, command.booking_id
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
            await self._spaces.get_resource(payload.principal, payload.resource_id)
            return await self._commands.execute(
                CreateBookingCommand(
                    payload.principal.tenant_id,
                    payload.principal.actor_id,
                    payload.resource_id,
                    payload.starts_at,
                    payload.ends_at,
                    payload.idempotency_key,
                )
            )
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
        resources = (
            [await self._spaces.get_resource(payload.principal, payload.resource_id)]
            if payload.resource_id
            else await self._spaces.list_resources(payload.principal)
        )
        return await self._queries.execute(
            AvailabilityQuery(
                payload.principal.tenant_id,
                payload.starts_at,
                payload.ends_at,
                tuple(resource.id for resource in resources),
            )
        )

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
    ) -> Booking:
        return await self._set(payload, "cancelled")

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
    [BookingRepository, OutboxRepository, AuditRepository]
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
        GetBookingHandler,
        ListBookingsHandler,
        AvailabilityHandler,
        FacilitiesDashboardHandler,
        SetBookingStatusHandler,
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


def _validate(command: CreateBookingCommand) -> None:
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
    )


def _as_utc(value: datetime) -> datetime:
    """SQLite does not round-trip timezone offsets despite timezone=True."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


if __name__ == "__main__":
    asyncio.run(run())
