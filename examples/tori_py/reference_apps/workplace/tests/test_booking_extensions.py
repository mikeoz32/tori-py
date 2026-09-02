"""Specifications for future booking rescheduling and recurrence support."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
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
    IdempotencyConflict,
    OutboxRepository,
    OutboxRow,
    RescheduleBookingCommand,
    RescheduleBookingHandler,
)
from examples.tori_py.reference_apps.workplace.bookings.app import (
    Base as BookingsBase,
)
from examples.tori_py.reference_apps.workplace.common.contracts import OfficePolicy


@pytest.fixture
async def booking_extensions():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(BookingsBase.metadata.create_all)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    bookings = BookingRepository(BookingRow, entities)
    operations = BookingOperationRepository(BookingOperationRow, entities)
    cancellation_operations = BookingCancellationOperationRepository(
        BookingCancellationOperationRow, entities
    )
    series = BookingSeriesRepository(BookingSeriesRow, entities)
    outbox = OutboxRepository(OutboxRow, entities)
    audit = AuditRepository(AuditRow, entities)
    try:
        yield {
            "bookings": bookings,
            "operations": operations,
            "cancellation_operations": cancellation_operations,
            "series": series,
            "outbox": outbox,
            "audit": audit,
            "create": CreateBookingHandler(entities, bookings, outbox, audit),
            "reschedule": RescheduleBookingHandler(
                entities, bookings, operations, outbox, audit
            ),
            "recurring": CreateRecurringBookingHandler(
                entities, bookings, series, outbox, audit
            ),
            "cancel": CancelBookingHandler(
                entities, bookings, cancellation_operations, outbox, audit
            ),
        }
    finally:
        await engine.dispose()


def booking_command(
    *,
    idempotency_key: str = "create-1",
    actor_id: str = "employee-1",
    resource_id: str = "desk-17",
    starts_at: datetime = datetime(2026, 9, 2, 9, tzinfo=UTC),
) -> CreateBookingCommand:
    return CreateBookingCommand(
        tenant_id="tenant-north",
        actor_id=actor_id,
        resource_id=resource_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        idempotency_key=idempotency_key,
    )


def reschedule_command(
    booking_id: str,
    *,
    actor_id: str = "employee-1",
    roles: tuple[str, ...] = ("employee",),
    idempotency_key: str = "reschedule-1",
    starts_at: datetime = datetime(2026, 9, 2, 12, tzinfo=UTC),
) -> RescheduleBookingCommand:
    return RescheduleBookingCommand(
        tenant_id="tenant-north",
        actor_id=actor_id,
        roles=roles,
        booking_id=booking_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        idempotency_key=idempotency_key,
    )


def recurring_command(
    *,
    recurrence: str = "daily",
    occurrence_count: int = 3,
    idempotency_key: str = "series-1",
    starts_at: datetime = datetime(2026, 10, 24, 9, tzinfo=UTC),
) -> CreateRecurringBookingCommand:
    return CreateRecurringBookingCommand(
        tenant_id="tenant-north",
        actor_id="employee-1",
        resource_id="desk-17",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        recurrence=recurrence,
        occurrence_count=occurrence_count,
        idempotency_key=idempotency_key,
    )


def office_policy(
    *,
    time_zone: str = "Europe/London",
    opens_at: str = "08:00",
    closes_at: str = "18:00",
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6),
) -> OfficePolicy:
    return OfficePolicy("office-north", time_zone, opens_at, closes_at, weekdays)


@pytest.mark.asyncio
async def test_reschedule_keeps_booking_identity_and_writes_rescheduled_records(
    booking_extensions,
) -> None:
    created = await booking_extensions["create"].handle(booking_command())

    rescheduled = await booking_extensions["reschedule"].handle(
        reschedule_command(created.id)
    )

    assert rescheduled.id == created.id
    assert rescheduled.resource_id == created.resource_id
    assert rescheduled.actor_id == created.actor_id
    assert rescheduled.status == "booked"
    assert rescheduled.starts_at == datetime(2026, 9, 2, 12, tzinfo=UTC)
    assert [
        event.event_name for event in await booking_extensions["outbox"].find()
    ] == [
        "booking-created",
        "booking-rescheduled",
    ]
    assert [row.action for row in await booking_extensions["audit"].find()] == [
        "booking-created",
        "booking-rescheduled",
    ]


@pytest.mark.asyncio
async def test_reschedule_allows_the_owner_or_a_facilities_administrator(
    booking_extensions,
) -> None:
    created = await booking_extensions["create"].handle(booking_command())

    with pytest.raises(PermissionError):
        await booking_extensions["reschedule"].handle(
            reschedule_command(created.id, actor_id="employee-2")
        )

    rescheduled = await booking_extensions["reschedule"].handle(
        reschedule_command(
            created.id,
            actor_id="facilities-1",
            roles=("facilities-admin",),
        )
    )
    assert rescheduled.actor_id == "employee-1"


@pytest.mark.asyncio
async def test_reschedule_excludes_itself_but_rejects_conflicts_atomically(
    booking_extensions,
) -> None:
    created = await booking_extensions["create"].handle(booking_command())
    blocking = await booking_extensions["create"].handle(
        booking_command(
            idempotency_key="blocking",
            resource_id=created.resource_id,
            starts_at=datetime(2026, 9, 2, 13, tzinfo=UTC),
        )
    )

    replayed_at_same_interval = await booking_extensions["reschedule"].handle(
        reschedule_command(
            created.id,
            idempotency_key="self-exclusion",
            starts_at=created.starts_at,
        )
    )
    assert replayed_at_same_interval.id == created.id

    with pytest.raises(BookingConflict):
        await booking_extensions["reschedule"].handle(
            reschedule_command(
                created.id,
                idempotency_key="conflicting-reschedule",
                starts_at=blocking.starts_at,
            )
        )

    persisted = await booking_extensions["bookings"].tenant_booking(
        "tenant-north", created.id
    )
    assert persisted is not None
    assert persisted.starts_at == created.starts_at
    assert await booking_extensions["operations"].count() == 1
    assert await booking_extensions["outbox"].count() == 3
    assert await booking_extensions["audit"].count() == 3


@pytest.mark.asyncio
async def test_reschedule_operation_idempotency_replays_or_rejects_changed_requests(
    booking_extensions,
) -> None:
    created = await booking_extensions["create"].handle(booking_command())
    command = reschedule_command(created.id)

    first = await booking_extensions["reschedule"].handle(command)
    repeated = await booking_extensions["reschedule"].handle(command)

    assert repeated == first
    assert await booking_extensions["operations"].count() == 1
    assert await booking_extensions["outbox"].count() == 2
    assert await booking_extensions["audit"].count() == 2
    with pytest.raises(IdempotencyConflict):
        await booking_extensions["reschedule"].handle(
            reschedule_command(
                created.id, starts_at=datetime(2026, 9, 2, 15, tzinfo=UTC)
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(("recurrence", "step"), (("daily", 1), ("weekly", 7)))
async def test_recurring_bookings_materialize_utc_occurrences_with_one_series(
    booking_extensions, recurrence: str, step: int
) -> None:
    occurrences = await booking_extensions["recurring"].handle(
        recurring_command(recurrence=recurrence)
    )
    rows = await booking_extensions["bookings"].find(
        BookingRow.id.in_([occurrence.id for occurrence in occurrences]),
        order_by=(BookingRow.occurrence_index,),
    )

    assert [row.occurrence_index for row in rows] == [0, 1, 2]
    assert len({row.series_id for row in rows}) == 1
    assert rows[0].series_id is not None
    assert [row.starts_at for row in rows] == [
        datetime(2026, 10, 24, 9, tzinfo=UTC) + timedelta(days=step * index)
        for index in range(3)
    ]
    assert all(row.status == "booked" for row in rows)
    assert await booking_extensions["series"].count() == 1


@pytest.mark.asyncio
async def test_recurring_booking_conflict_rolls_back_the_entire_series(
    booking_extensions,
) -> None:
    await booking_extensions["create"].handle(
        booking_command(
            starts_at=datetime(2026, 10, 25, 9, tzinfo=UTC),
            idempotency_key="existing-conflict",
        )
    )

    with pytest.raises(BookingConflict):
        await booking_extensions["recurring"].handle(recurring_command())

    assert await booking_extensions["bookings"].count() == 1
    assert await booking_extensions["series"].count() == 0
    assert await booking_extensions["outbox"].count() == 1
    assert await booking_extensions["audit"].count() == 1


@pytest.mark.asyncio
async def test_recurring_series_idempotency_replays_without_duplicate_side_effects(
    booking_extensions,
) -> None:
    command = recurring_command()

    first = await booking_extensions["recurring"].handle(command)
    repeated = await booking_extensions["recurring"].handle(command)

    assert repeated == first
    assert await booking_extensions["bookings"].count() == 3
    assert await booking_extensions["series"].count() == 1
    assert await booking_extensions["outbox"].count() == 3
    assert await booking_extensions["audit"].count() == 3
    with pytest.raises(IdempotencyConflict):
        await booking_extensions["recurring"].handle(
            recurring_command(occurrence_count=4)
        )


@pytest.mark.asyncio
async def test_inactive_resources_reject_new_booking_mutations(
    booking_extensions,
) -> None:
    with pytest.raises(BookingConflict, match="resource is inactive"):
        await booking_extensions["create"].handle(
            replace(booking_command(), resource_active=False)
        )
    with pytest.raises(BookingConflict, match="resource is inactive"):
        await booking_extensions["recurring"].handle(
            replace(recurring_command(), resource_active=False)
        )

    created = await booking_extensions["create"].handle(
        booking_command(idempotency_key="reschedule-source")
    )
    with pytest.raises(BookingConflict, match="resource is inactive"):
        await booking_extensions["reschedule"].handle(
            replace(reschedule_command(created.id), resource_active=False)
        )


@pytest.mark.asyncio
async def test_accepted_booking_mutations_replay_after_resource_deactivation(
    booking_extensions,
) -> None:
    create = booking_command()
    created = await booking_extensions["create"].handle(create)
    assert (
        await booking_extensions["create"].handle(
            replace(create, resource_active=False)
        )
        == created
    )

    recurring = recurring_command()
    occurrences = await booking_extensions["recurring"].handle(recurring)
    assert (
        await booking_extensions["recurring"].handle(
            replace(recurring, resource_active=False)
        )
        == occurrences
    )

    reschedule = reschedule_command(created.id)
    rescheduled = await booking_extensions["reschedule"].handle(reschedule)
    assert (
        await booking_extensions["reschedule"].handle(
            replace(reschedule, resource_active=False)
        )
        == rescheduled
    )


@pytest.mark.asyncio
async def test_office_policy_rejects_closed_periods_for_create_and_reschedule(
    booking_extensions,
) -> None:
    policy = office_policy(
        opens_at="09:00", closes_at="17:00", weekdays=(0, 1, 2, 3, 4)
    )
    monday = datetime(2026, 9, 7, 7, tzinfo=UTC)

    with pytest.raises(ValueError, match="office hours"):
        await booking_extensions["create"].handle(
            replace(booking_command(starts_at=monday), office_policy=policy)
        )

    created = await booking_extensions["create"].handle(
        booking_command(
            idempotency_key="inside-hours", starts_at=monday + timedelta(hours=2)
        )
    )
    with pytest.raises(ValueError, match="office hours"):
        await booking_extensions["reschedule"].handle(
            replace(
                reschedule_command(created.id, starts_at=monday),
                office_policy=policy,
            )
        )


@pytest.mark.asyncio
async def test_daily_recurrence_preserves_office_wall_time_across_dst(
    booking_extensions,
) -> None:
    policy = office_policy()
    command = replace(
        recurring_command(
            starts_at=datetime(2026, 10, 24, 8, tzinfo=UTC), occurrence_count=3
        ),
        office_policy=policy,
    )

    occurrences = await booking_extensions["recurring"].handle(command)

    assert [booking.starts_at for booking in occurrences] == [
        datetime(2026, 10, 24, 8, tzinfo=UTC),
        datetime(2026, 10, 25, 9, tzinfo=UTC),
        datetime(2026, 10, 26, 9, tzinfo=UTC),
    ]


@pytest.mark.asyncio
async def test_office_policy_rejects_seconds_past_closing(booking_extensions) -> None:
    starts_at = datetime(2026, 9, 7, 15, tzinfo=UTC)
    command = replace(
        booking_command(starts_at=starts_at),
        ends_at=datetime(2026, 9, 7, 16, 0, 30, tzinfo=UTC),
        office_policy=office_policy(closes_at="17:00"),
    )

    with pytest.raises(ValueError, match="office hours"):
        await booking_extensions["create"].handle(command)


@pytest.mark.asyncio
async def test_weekly_recurrence_preserves_office_wall_time_across_dst(
    booking_extensions,
) -> None:
    command = replace(
        recurring_command(
            recurrence="weekly",
            occurrence_count=2,
            starts_at=datetime(2026, 10, 18, 8, tzinfo=UTC),
        ),
        office_policy=office_policy(),
    )

    occurrences = await booking_extensions["recurring"].handle(command)

    assert [booking.starts_at for booking in occurrences] == [
        datetime(2026, 10, 18, 8, tzinfo=UTC),
        datetime(2026, 10, 25, 9, tzinfo=UTC),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "starts_at",
    (
        datetime(2026, 3, 28, 1, 30, tzinfo=UTC),
        datetime(2026, 10, 24, 0, 30, tzinfo=UTC),
    ),
)
async def test_daily_recurrence_rejects_nonexistent_or_ambiguous_office_time(
    booking_extensions, starts_at: datetime
) -> None:
    command = replace(
        recurring_command(occurrence_count=2, starts_at=starts_at),
        office_policy=office_policy(opens_at="00:00", closes_at="23:59"),
    )

    with pytest.raises(ValueError, match="ambiguous or nonexistent"):
        await booking_extensions["recurring"].handle(command)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "expected_indexes"),
    (("one", [1]), ("this-and-following", [1, 2]), ("entire-series", [0, 1, 2])),
)
async def test_scoped_series_cancellation_is_atomic_and_idempotent(
    booking_extensions, scope: str, expected_indexes: list[int]
) -> None:
    occurrences = await booking_extensions["recurring"].handle(recurring_command())
    command = CancelBookingCommand(
        tenant_id="tenant-north",
        actor_id="employee-1",
        roles=("employee",),
        booking_id=occurrences[1].id,
        scope=scope,
        idempotency_key=f"cancel-{scope}",
    )

    cancelled = await booking_extensions["cancel"].handle(command)
    replayed = await booking_extensions["cancel"].handle(command)

    assert [booking.occurrence_index for booking in cancelled] == expected_indexes
    assert replayed == cancelled
    assert await booking_extensions["cancellation_operations"].count() == 1
    rows = await booking_extensions["bookings"].find(
        BookingRow.series_id == occurrences[0].series_id,
        order_by=(BookingRow.occurrence_index,),
    )
    assert [row.status for row in rows] == [
        "cancelled" if index in expected_indexes else "booked" for index in range(3)
    ]
    assert len(await booking_extensions["outbox"].find()) == 3 + len(expected_indexes)
    assert len(await booking_extensions["audit"].find()) == 3 + len(expected_indexes)


@pytest.mark.asyncio
async def test_scoped_cancellation_rejects_changed_replay_and_other_owner(
    booking_extensions,
) -> None:
    occurrences = await booking_extensions["recurring"].handle(recurring_command())
    command = CancelBookingCommand(
        "tenant-north",
        "employee-1",
        ("employee",),
        occurrences[0].id,
        "one",
        "cancel-1",
    )
    await booking_extensions["cancel"].handle(command)

    with pytest.raises(IdempotencyConflict):
        await booking_extensions["cancel"].handle(
            replace(command, scope="entire-series")
        )
    with pytest.raises(PermissionError):
        await booking_extensions["cancel"].handle(
            replace(command, actor_id="employee-2", idempotency_key="cancel-2")
        )
