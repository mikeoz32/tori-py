"""Specifications for notification delivery of extended booking events."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tori_py_sqlalchemy import EntityManager

from examples.tori_py.reference_apps.workplace.common.contracts import (
    BookingCreated,
    BookingLifecycleEvent,
    BookingRescheduled,
)
from examples.tori_py.reference_apps.workplace.notifications.app import (
    Base,
    InboxConflict,
    NotificationInboxRepository,
    NotificationInboxRow,
    NotificationRepository,
    NotificationRow,
    NotificationsController,
)
from examples.tori_py.reference_apps.workplace.notifications.migrate import migrate


def _controller(database_url: str):
    engine = create_async_engine(database_url)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    notifications = NotificationRepository(NotificationRow, entities)
    inbox = NotificationInboxRepository(NotificationInboxRow, entities)
    return (
        NotificationsController(entities, notifications, inbox),
        notifications,
        inbox,
        engine,
    )


@pytest.mark.asyncio
async def test_booking_rescheduled_records_one_readable_idempotent_notification() -> (
    None
):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    notifications = NotificationRepository(NotificationRow, entities)
    inbox = NotificationInboxRepository(NotificationInboxRow, entities)
    controller = NotificationsController(entities, notifications, inbox)
    event = BookingRescheduled(
        "tenant-north",
        "booking-17",
        "employee-1",
        "desk-17",
        datetime(2026, 9, 2, 12, tzinfo=UTC),
        datetime(2026, 9, 2, 14, tzinfo=UTC),
    )

    try:
        await controller.booking_rescheduled(event, "event-rescheduled-1")
        await controller.booking_rescheduled(event, "event-rescheduled-1")

        rows = await notifications.find()
        assert len(rows) == 1
        assert rows[0].tenant_id == "tenant-north"
        assert rows[0].event_id == "event-rescheduled-1"
        assert rows[0].message == "Booking booking-17 rescheduled"
        assert await inbox.count() == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reusing_an_event_id_for_different_payload_is_rejected() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    notifications = NotificationRepository(NotificationRow, entities)
    inbox = NotificationInboxRepository(NotificationInboxRow, entities)
    controller = NotificationsController(entities, notifications, inbox)
    event = BookingRescheduled(
        "tenant-north",
        "booking-17",
        "employee-1",
        "desk-17",
        datetime(2026, 9, 2, 12, tzinfo=UTC),
        datetime(2026, 9, 2, 14, tzinfo=UTC),
    )

    try:
        await controller.booking_rescheduled(event, "event-rescheduled-1")
        with pytest.raises(InboxConflict):
            await controller.booking_rescheduled(
                BookingRescheduled(
                    event.tenant_id,
                    "booking-18",
                    event.actor_id,
                    event.resource_id,
                    event.starts_at,
                    event.ends_at,
                ),
                "event-rescheduled-1",
            )

        assert await notifications.count() == 1
        assert await inbox.count() == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_existing_notification_is_adopted_into_the_inbox() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    notifications = NotificationRepository(NotificationRow, entities)
    inbox = NotificationInboxRepository(NotificationInboxRow, entities)
    controller = NotificationsController(entities, notifications, inbox)
    event = BookingCreated("tenant-north", "booking-17", "employee-1", "desk-17")

    try:
        async with entities.transaction():
            await notifications.add(
                NotificationRow(
                    id="legacy-notification-1",
                    tenant_id=event.tenant_id,
                    event_id="legacy-event-1",
                    message="Booking booking-17 created",
                    created_at=datetime(2026, 9, 2, 12, tzinfo=UTC),
                )
            )

        await controller.booking_created(event, "legacy-event-1")

        assert await notifications.count() == 1
        assert await inbox.count() == 1
        with pytest.raises(InboxConflict):
            await controller.booking_created(
                BookingCreated(
                    event.tenant_id,
                    event.booking_id,
                    "different-employee",
                    "different-desk",
                ),
                "legacy-event-1",
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_notification_failure_rolls_back_the_inbox_record() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    inbox = NotificationInboxRepository(NotificationInboxRow, entities)

    class FailingNotificationRepository(NotificationRepository):
        async def add(self, entity: NotificationRow) -> NotificationRow:
            del entity
            raise RuntimeError("notification projection failed")

    notifications = FailingNotificationRepository(NotificationRow, entities)
    controller = NotificationsController(entities, notifications, inbox)
    event = BookingCreated("tenant-north", "booking-17", "employee-1", "desk-17")

    try:
        with pytest.raises(RuntimeError, match="projection failed"):
            await controller.booking_created(event, "event-created-1")

        assert await inbox.count() == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_lifecycle_route_must_match_the_payload_status() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    notifications = NotificationRepository(NotificationRow, entities)
    inbox = NotificationInboxRepository(NotificationInboxRow, entities)
    controller = NotificationsController(entities, notifications, inbox)

    try:
        with pytest.raises(InboxConflict, match="event type does not match"):
            await controller.booking_checked_in(
                BookingLifecycleEvent(
                    "tenant-north",
                    "booking-17",
                    "employee-1",
                    "desk-17",
                    "cancelled",
                ),
                "mismatched-route-1",
            )

        assert await notifications.count() == 0
        assert await inbox.count() == 0
    finally:
        await engine.dispose()


@pytest.fixture
async def migrated_notifications_postgres(
    postgres_url: str, monkeypatch: pytest.MonkeyPatch
):
    schema = f"notification_test_{uuid4().hex}"
    engine = create_async_engine(postgres_url)
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await engine.dispose()

    database_url = f"{postgres_url}?options=-csearch_path%3D{schema}"
    monkeypatch.setenv("WORKPLACE_NOTIFICATIONS_DATABASE_URL", database_url)
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
        finally:
            await cleanup_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_concurrent_duplicate_delivery_commits_one_inbox_record(
    migrated_notifications_postgres: str,
) -> None:
    first, _, _, first_engine = _controller(migrated_notifications_postgres)
    second, notifications, inbox, second_engine = _controller(
        migrated_notifications_postgres
    )
    event = BookingRescheduled(
        "tenant-north",
        "booking-17",
        "employee-1",
        "desk-17",
        datetime(2026, 9, 2, 12, tzinfo=UTC),
        datetime(2026, 9, 2, 14, tzinfo=UTC),
    )

    try:
        await asyncio.gather(
            first.booking_rescheduled(event, "concurrent-event-1"),
            second.booking_rescheduled(event, "concurrent-event-1"),
        )

        assert await notifications.count() == 1
        assert await inbox.count() == 1
    finally:
        await first_engine.dispose()
        await second_engine.dispose()
