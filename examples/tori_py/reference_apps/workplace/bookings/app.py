"""Tenant-isolated booking service with explicit idempotency semantics."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, select
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
    Booking,
    BookingCreated,
    CancelBooking,
    CheckInBooking,
    CreateBooking,
    GetBooking,
    Health,
    ListBookings,
    Principal,
)
from ..common.infrastructure import rabbit_modules, serve, sql_module
from ..common.security import has_workplace_role
from ..common.services import BOOKINGS, BookingsService, SpacesService

MAX_BOOKING_DURATION = timedelta(hours=24)
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
    payload: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    async def next_pending(self) -> OutboxRow | None:
        rows = await self.find(OutboxRow.published_at.is_(None), limit=1)
        return rows[0] if rows else None


class IdempotencyConflict(Exception):
    pass


class BookingConflict(Exception):
    pass


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
    ) -> None:
        self._entities, self._bookings, self._outbox = entities, bookings, outbox

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
        return [_booking(row) for row in await self._bookings.find(*filters)]


@command_handler(SetBookingStatusCommand)
class SetBookingStatusHandler:
    def __init__(self, entities: EntityManager, bookings: BookingRepository) -> None:
        self._entities, self._bookings = entities, bookings

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
            if command.status == "checked_in" and row.status != "booked":
                raise BookingConflict("only a booked reservation can be checked in")
            if command.status == "cancelled" and row.status == "cancelled":
                return _booking(row)
            row.status = command.status
            await self._entities.flush()
            return _booking(row)


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
        async with self._entities.transaction():
            row = await self._outbox.next_pending()
            if row is None:
                return False
            row.attempts += 1
            event_id, payload = row.event_id, json.loads(row.payload)
            await self._entities.flush()
        await self._events.publish(
            "booking-created",
            1,
            payload,
            headers={"outbox_event_id": event_id},
            require_route=True,
        )
        async with self._entities.transaction():
            row = await self._outbox.get(event_id)
            if row is not None:
                row.published_at = utc_now()
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
    ) -> None:
        self._commands, self._queries = commands, queries
        self._entities, self._spaces = entities, spaces

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
            )
        )

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
bookings_feature = SqlAlchemyModule.for_feature([BookingRepository, OutboxRepository])
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
        SetBookingStatusHandler,
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
    for instant in (command.starts_at, command.ends_at):
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("booking times must be timezone-aware")
        if instant.utcoffset() != timedelta(0):
            raise ValueError("booking times must be UTC")
    if (
        command.starts_at >= command.ends_at
        or command.ends_at - command.starts_at > MAX_BOOKING_DURATION
    ):
        raise ValueError("booking period is invalid")


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
