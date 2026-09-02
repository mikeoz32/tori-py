"""PostgreSQL specifications for booking exclusion and transaction atomicity."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from tori_py_microservices import EventDispatcher
from tori_py_sqlalchemy import EntityManager

from examples.tori_py.reference_apps.workplace.bookings.app import (
    AuditRepository,
    AuditRow,
    BookingCancellationOperationRepository,
    BookingCancellationOperationRow,
    BookingConflict,
    BookingOperationRepository,
    BookingOperationRow,
    BookingRepository,
    BookingRow,
    BookingSeriesRepository,
    BookingSeriesRow,
    CancelBookingCommand,
    CancelBookingHandler,
    CreateBookingCommand,
    CreateBookingHandler,
    CreateRecurringBookingCommand,
    CreateRecurringBookingHandler,
    OutboxRelay,
    OutboxRepository,
    OutboxRow,
    RescheduleBookingCommand,
    RescheduleBookingHandler,
    SetBookingStatusCommand,
    SetBookingStatusHandler,
)
from examples.tori_py.reference_apps.workplace.bookings.migrate import migrate


@pytest.fixture
async def migrated_postgres(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    """Run the production migration against an isolated schema in PostgreSQL."""
    schema = f"booking_test_{uuid4().hex}"
    decoy_schema = f"booking_decoy_{uuid4().hex}"
    engine = create_async_engine(postgres_url)
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'CREATE SCHEMA "{decoy_schema}"'))
        await connection.execute(
            text(
                f'CREATE TABLE "{decoy_schema}".bookings '
                "(id INTEGER CONSTRAINT bookings_no_overlap CHECK (id > 0))"
            )
        )
    await engine.dispose()

    database_url = f"{postgres_url}?options=-csearch_path%3D{schema}"
    monkeypatch.setenv("WORKPLACE_BOOKINGS_DATABASE_URL", database_url)
    try:
        await migrate()
        yield database_url
    finally:
        cleanup_engine = create_async_engine(postgres_url)
        try:
            async with cleanup_engine.begin() as connection:
                await connection.execute(
                    text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                )
                await connection.execute(
                    text(f'DROP SCHEMA IF EXISTS "{decoy_schema}" CASCADE')
                )
        finally:
            await cleanup_engine.dispose()


def _handler(database_url: str) -> tuple[CreateBookingHandler, AsyncEngine]:
    engine = create_async_engine(database_url)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    bookings = BookingRepository(BookingRow, entities)
    outbox = OutboxRepository(OutboxRow, entities)
    audit = AuditRepository(AuditRow, entities)
    return CreateBookingHandler(entities, bookings, outbox, audit), engine


def _extension_handlers(
    database_url: str,
) -> tuple[
    CreateBookingHandler,
    CreateRecurringBookingHandler,
    RescheduleBookingHandler,
    AsyncEngine,
]:
    engine = create_async_engine(database_url)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    bookings = BookingRepository(BookingRow, entities)
    operations = BookingOperationRepository(BookingOperationRow, entities)
    series = BookingSeriesRepository(BookingSeriesRow, entities)
    outbox = OutboxRepository(OutboxRow, entities)
    audit = AuditRepository(AuditRow, entities)
    return (
        CreateBookingHandler(entities, bookings, outbox, audit),
        CreateRecurringBookingHandler(entities, bookings, series, outbox, audit),
        RescheduleBookingHandler(entities, bookings, operations, outbox, audit),
        engine,
    )


class _ReadBarrier:
    def __init__(self) -> None:
        self.ready = asyncio.Event()
        self.readers = 0


class _RacingBookingRepository(BookingRepository):
    def __init__(self, entities: EntityManager, barrier: _ReadBarrier) -> None:
        super().__init__(BookingRow, entities)
        self._barrier = barrier

    async def tenant_booking(
        self, tenant_id: str, booking_id: str, *, for_update: bool = False
    ) -> BookingRow | None:
        row = await super().tenant_booking(tenant_id, booking_id, for_update=for_update)
        if not for_update:
            self._barrier.readers += 1
            if self._barrier.readers == 2:
                self._barrier.ready.set()
            await self._barrier.ready.wait()
        return row


def _status_handler(
    database_url: str, barrier: _ReadBarrier
) -> tuple[SetBookingStatusHandler, AsyncEngine]:
    engine = create_async_engine(database_url)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    bookings = _RacingBookingRepository(entities, barrier)
    return (
        SetBookingStatusHandler(
            entities,
            bookings,
            OutboxRepository(OutboxRow, entities),
            AuditRepository(AuditRow, entities),
        ),
        engine,
    )


def _cancellation_handler(
    database_url: str,
) -> tuple[CancelBookingHandler, AsyncEngine]:
    engine = create_async_engine(database_url)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    return (
        CancelBookingHandler(
            entities,
            BookingRepository(BookingRow, entities),
            BookingCancellationOperationRepository(
                BookingCancellationOperationRow, entities
            ),
            OutboxRepository(OutboxRow, entities),
            AuditRepository(AuditRow, entities),
        ),
        engine,
    )


def _command(
    tenant_id: str,
    idempotency_key: str,
    starts_at: datetime = datetime(2026, 9, 2, 9, tzinfo=UTC),
) -> CreateBookingCommand:
    return CreateBookingCommand(
        tenant_id=tenant_id,
        actor_id=f"employee-{idempotency_key}",
        resource_id="desk-17",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        idempotency_key=idempotency_key,
    )


def _recurring_command(
    idempotency_key: str,
) -> CreateRecurringBookingCommand:
    starts_at = datetime(2026, 9, 2, 9, tzinfo=UTC)
    return CreateRecurringBookingCommand(
        tenant_id="tenant-north",
        actor_id=f"employee-{idempotency_key}",
        resource_id="desk-17",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        recurrence="daily",
        occurrence_count=3,
        idempotency_key=idempotency_key,
    )


def _reschedule_command(
    booking_id: str, idempotency_key: str
) -> RescheduleBookingCommand:
    starts_at = datetime(2026, 9, 2, 12, tzinfo=UTC)
    return RescheduleBookingCommand(
        tenant_id="tenant-north",
        actor_id="employee-original",
        roles=("employee",),
        booking_id=booking_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        idempotency_key=idempotency_key,
    )


async def _submit(
    handler: CreateBookingHandler, command: CreateBookingCommand
) -> object:
    try:
        return await handler.handle(command)
    except BookingConflict as error:
        return error


async def _submit_recurring(
    handler: CreateRecurringBookingHandler, command: CreateRecurringBookingCommand
) -> object:
    try:
        return await handler.handle(command)
    except BookingConflict as error:
        return error


async def _submit_reschedule(
    handler: RescheduleBookingHandler, command: RescheduleBookingCommand
) -> object:
    try:
        return await handler.handle(command)
    except BookingConflict as error:
        return error


async def _row_counts(database_url: str) -> tuple[int, int, int]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            counts: list[int] = []
            for table in ("bookings", "outbox", "booking_audit"):
                statement = text(f"SELECT count(*) FROM {table}")
                counts.append(int(await connection.scalar(statement) or 0))
            return counts[0], counts[1], counts[2]
    finally:
        await engine.dispose()


async def _extension_row_counts(database_url: str) -> tuple[int, int, int, int, int]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            counts: list[int] = []
            for table in (
                "bookings",
                "booking_series",
                "booking_operations",
                "outbox",
                "booking_audit",
            ):
                statement = text(f"SELECT count(*) FROM {table}")
                counts.append(int(await connection.scalar(statement) or 0))
            return counts[0], counts[1], counts[2], counts[3], counts[4]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_exclusion_constraint_makes_concurrent_overlap_atomic(
    migrated_postgres: str,
) -> None:
    first, first_engine = _handler(migrated_postgres)
    second, second_engine = _handler(migrated_postgres)
    try:
        results = await asyncio.gather(
            _submit(first, _command("tenant-north", "first")),
            _submit(second, _command("tenant-north", "second")),
        )
        successes = [result for result in results if not isinstance(result, Exception)]
        conflicts = [
            result for result in results if isinstance(result, BookingConflict)
        ]

        assert len(successes) == 1
        assert len(conflicts) == 1
        assert await _row_counts(migrated_postgres) == (1, 1, 1)
    finally:
        await first_engine.dispose()
        await second_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_overlap_is_isolated_by_tenant(
    migrated_postgres: str,
) -> None:
    north, north_engine = _handler(migrated_postgres)
    south, south_engine = _handler(migrated_postgres)
    try:
        results = await asyncio.gather(
            _submit(north, _command("tenant-north", "north")),
            _submit(south, _command("tenant-south", "south")),
        )

        assert not any(isinstance(result, Exception) for result in results)
        assert await _row_counts(migrated_postgres) == (2, 2, 2)
    finally:
        await north_engine.dispose()
        await south_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_outbox_claim_allows_only_one_concurrent_publisher(
    migrated_postgres: str,
) -> None:
    create, create_engine = _handler(migrated_postgres)
    await create.handle(_command("tenant-north", "outbox-claim"))

    class BlockingEvents:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.event_ids: list[str] = []

        async def publish(self, *args, **kwargs) -> None:
            self.event_ids.append(kwargs["headers"]["outbox_event_id"])
            self.started.set()
            await self.release.wait()

    events = BlockingEvents()
    first_engine = create_async_engine(migrated_postgres)
    second_engine = create_async_engine(migrated_postgres)
    first_entities = EntityManager(
        async_sessionmaker(first_engine, expire_on_commit=False)
    )
    second_entities = EntityManager(
        async_sessionmaker(second_engine, expire_on_commit=False)
    )
    first_outbox = OutboxRepository(OutboxRow, first_entities)
    second_outbox = OutboxRepository(OutboxRow, second_entities)
    first = OutboxRelay(first_entities, first_outbox, cast(EventDispatcher, events))
    second = OutboxRelay(second_entities, second_outbox, cast(EventDispatcher, events))

    try:
        publication = asyncio.create_task(first.publish_once())
        await asyncio.wait_for(events.started.wait(), timeout=5)
        assert await asyncio.wait_for(second.publish_once(), timeout=1) is False
        events.release.set()
        assert await publication is True
        assert len(events.event_ids) == 1

        row = await first_outbox.find_one(OutboxRow.tenant_id == "tenant-north")
        assert row is not None
        assert row.published_at is not None
    finally:
        events.release.set()
        await create_engine.dispose()
        await first_engine.dispose()
        await second_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_recurring_conflict_on_later_occurrence_is_atomic(
    migrated_postgres: str,
) -> None:
    ordinary, _, _, ordinary_engine = _extension_handlers(migrated_postgres)
    _, recurring, _, recurring_engine = _extension_handlers(migrated_postgres)
    try:
        ordinary_command = _command(
            "tenant-north",
            "ordinary-later-occurrence",
            datetime(2026, 9, 3, 9, tzinfo=UTC),
        )
        results = await asyncio.gather(
            _submit_recurring(
                recurring, _recurring_command("recurring-later-occurrence")
            ),
            _submit(ordinary, ordinary_command),
        )

        assert sum(isinstance(result, BookingConflict) for result in results) == 1
        successful_series = [result for result in results if isinstance(result, list)]
        assert len(successful_series) <= 1
        assert await _extension_row_counts(migrated_postgres) in (
            (3, 1, 0, 3, 3),
            (1, 0, 0, 1, 1),
        )
    finally:
        await ordinary_engine.dispose()
        await recurring_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_concurrent_recurring_idempotency_replays_one_series(
    migrated_postgres: str,
) -> None:
    _, first, _, first_engine = _extension_handlers(migrated_postgres)
    _, second, _, second_engine = _extension_handlers(migrated_postgres)
    command = _recurring_command("same-recurring-request")
    try:
        first_result, second_result = await asyncio.gather(
            first.handle(command), second.handle(command)
        )

        assert first_result == second_result
        assert len(first_result) == 3
        assert await _extension_row_counts(migrated_postgres) == (3, 1, 0, 3, 3)
    finally:
        await first_engine.dispose()
        await second_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_concurrent_reschedule_and_booking_are_atomic(
    migrated_postgres: str,
) -> None:
    create, _, reschedule, create_engine = _extension_handlers(migrated_postgres)
    ordinary, _, _, ordinary_engine = _extension_handlers(migrated_postgres)
    original = await create.handle(_command("tenant-north", "original"))
    try:
        results = await asyncio.gather(
            _submit_reschedule(
                reschedule, _reschedule_command(original.id, "reschedule")
            ),
            _submit(
                ordinary,
                CreateBookingCommand(
                    tenant_id="tenant-north",
                    actor_id="employee-ordinary",
                    resource_id="desk-17",
                    starts_at=datetime(2026, 9, 2, 12, tzinfo=UTC),
                    ends_at=datetime(2026, 9, 2, 14, tzinfo=UTC),
                    idempotency_key="ordinary-target-slot",
                ),
            ),
        )

        assert sum(isinstance(result, BookingConflict) for result in results) == 1
        assert sum(not isinstance(result, Exception) for result in results) == 1
        if any(getattr(result, "id", None) == original.id for result in results):
            assert await _extension_row_counts(migrated_postgres) == (1, 0, 1, 2, 2)
        else:
            assert await _extension_row_counts(migrated_postgres) == (2, 0, 0, 2, 2)
    finally:
        await create_engine.dispose()
        await ordinary_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_concurrent_reschedule_idempotency_replays_one_operation(
    migrated_postgres: str,
) -> None:
    create, _, first, create_engine = _extension_handlers(migrated_postgres)
    _, _, second, second_engine = _extension_handlers(migrated_postgres)
    original = await create.handle(_command("tenant-north", "original"))
    command = _reschedule_command(original.id, "same-reschedule-request")
    try:
        first_result, second_result = await asyncio.gather(
            first.handle(command), second.handle(command)
        )

        assert first_result == second_result
        assert first_result.id == original.id
        assert await _extension_row_counts(migrated_postgres) == (1, 0, 1, 2, 2)
    finally:
        await create_engine.dispose()
        await second_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_concurrent_status_transitions_follow_a_legal_sequence(
    migrated_postgres: str,
) -> None:
    create, create_engine = _handler(migrated_postgres)
    booking = await create.handle(_command("tenant-north", "status-race"))
    barrier = _ReadBarrier()
    check_in, check_in_engine = _status_handler(migrated_postgres, barrier)
    cancel, cancel_engine = _status_handler(migrated_postgres, barrier)

    async def transition(handler: SetBookingStatusHandler, status: str) -> object:
        try:
            return await handler.handle(
                SetBookingStatusCommand(
                    "tenant-north", booking.actor_id, ("employee",), booking.id, status
                )
            )
        except BookingConflict as error:
            return error

    try:
        results = await asyncio.gather(
            transition(check_in, "checked_in"), transition(cancel, "cancelled")
        )
        assert any(not isinstance(result, Exception) for result in results)

        engine = create_async_engine(migrated_postgres)
        try:
            async with engine.connect() as connection:
                status = await connection.scalar(
                    text("SELECT status FROM bookings WHERE id = :id"),
                    {"id": booking.id},
                )
                transitions = (
                    await connection.execute(
                        text(
                            "SELECT from_status, to_status FROM booking_audit "
                            "WHERE booking_id = :id AND from_status IS NOT NULL"
                        ),
                        {"id": booking.id},
                    )
                ).all()
        finally:
            await engine.dispose()

        assert status == "cancelled"
        assert sum(row.from_status == "booked" for row in transitions) == 1
    finally:
        barrier.ready.set()
        await create_engine.dispose()
        await check_in_engine.dispose()
        await cancel_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_concurrent_series_cancellation_replays_one_operation(
    migrated_postgres: str,
) -> None:
    _, recurring, _, create_engine = _extension_handlers(migrated_postgres)
    occurrences = await recurring.handle(_recurring_command("cancel-series-source"))
    first, first_engine = _cancellation_handler(migrated_postgres)
    second, second_engine = _cancellation_handler(migrated_postgres)
    command = CancelBookingCommand(
        "tenant-north",
        occurrences[0].actor_id,
        ("employee",),
        occurrences[1].id,
        "entire-series",
        "same-series-cancellation",
    )
    try:
        first_result, second_result = await asyncio.gather(
            first.handle(command), second.handle(command)
        )

        assert first_result == second_result
        assert [booking.status for booking in first_result] == ["cancelled"] * 3
        engine = create_async_engine(migrated_postgres)
        try:
            async with engine.connect() as connection:
                operations = await connection.scalar(
                    text("SELECT count(*) FROM booking_cancellation_operations")
                )
                events = await connection.scalar(
                    text(
                        "SELECT count(*) FROM outbox "
                        "WHERE event_name = 'booking-cancelled'"
                    )
                )
        finally:
            await engine.dispose()
        assert operations == 1
        assert events == 3
    finally:
        await create_engine.dispose()
        await first_engine.dispose()
        await second_engine.dispose()
