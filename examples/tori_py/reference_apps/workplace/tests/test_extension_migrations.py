"""Upgrade-path checks for workplace extension schemas."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from examples.tori_py.reference_apps.workplace.bookings.migrate import (
    migrate as migrate_bookings,
)
from examples.tori_py.reference_apps.workplace.notifications.migrate import (
    migrate as migrate_notifications,
)
from examples.tori_py.reference_apps.workplace.spaces.migrate import (
    migrate as migrate_spaces,
)


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


@pytest.mark.asyncio
async def test_spaces_migration_upgrades_existing_resources_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _sqlite_url(tmp_path / "spaces.db")
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text("""
            CREATE TABLE resources (
                id VARCHAR(36) PRIMARY KEY,
                tenant_id VARCHAR(128) NOT NULL,
                office_id VARCHAR(128) NOT NULL,
                floor_id VARCHAR(128) NOT NULL,
                name VARCHAR(128) NOT NULL,
                kind VARCHAR(16) NOT NULL,
                x INTEGER NOT NULL,
                y INTEGER NOT NULL
            )
            """)
        )
        await connection.execute(
            text("""
            INSERT INTO resources
                (id, tenant_id, office_id, floor_id, name, kind, x, y)
            VALUES
                ('legacy-desk', 'tenant-north', 'legacy-office', 'legacy-floor',
                 'Legacy desk', 'desk', 10, 20)
            """)
        )
    await engine.dispose()
    monkeypatch.setenv("WORKPLACE_SPACES_DATABASE_URL", database_url)

    await migrate_spaces()
    await migrate_spaces()

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            columns = {
                row[1]
                for row in await connection.execute(
                    text("PRAGMA table_info(resources)")
                )
            }
            legacy = (
                await connection.execute(
                    text("""
                    SELECT equipment_json, capacity, active
                    FROM resources WHERE id = 'legacy-desk'
                    """)
                )
            ).one()
            seeded = await connection.scalar(text("SELECT count(*) FROM resources"))
    finally:
        await engine.dispose()

    assert {"equipment_json", "capacity", "active"} <= columns
    assert tuple(legacy) == ("[]", 1, 1)
    assert seeded == 15

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            tables = {
                row[0]
                for row in await connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'table'")
                )
            }
            policies = await connection.scalar(
                text("SELECT count(*) FROM office_policies")
            )
            legacy_policy = (
                await connection.execute(
                    text(
                        """
                        SELECT time_zone, opens_at_minute, closes_at_minute,
                               weekdays_json
                        FROM office_policies
                        WHERE tenant_id = 'tenant-north'
                          AND office_id = 'legacy-office'
                        """
                    )
                )
            ).one()
            equipment = await connection.scalar(
                text("SELECT count(*) FROM resource_equipment")
            )
    finally:
        await engine.dispose()

    assert {"office_policies", "resource_equipment"} <= tables
    assert policies == 3
    assert tuple(legacy_policy) == (
        "UTC",
        0,
        1439,
        "[0, 1, 2, 3, 4, 5, 6]",
    )
    assert equipment == 28


@pytest.mark.asyncio
async def test_bookings_migration_upgrades_existing_bookings_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _sqlite_url(tmp_path / "bookings.db")
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text("""
            CREATE TABLE bookings (
                id VARCHAR(36) PRIMARY KEY,
                tenant_id VARCHAR(128) NOT NULL,
                actor_id VARCHAR(128) NOT NULL,
                resource_id VARCHAR(128) NOT NULL,
                starts_at DATETIME NOT NULL,
                ends_at DATETIME NOT NULL,
                status VARCHAR(16) NOT NULL,
                idempotency_key VARCHAR(128) NOT NULL,
                request_fingerprint VARCHAR(64) NOT NULL,
                UNIQUE (tenant_id, idempotency_key)
            )
            """)
        )
        await connection.execute(
            text("""
            CREATE TABLE outbox (
                event_id VARCHAR(36) PRIMARY KEY,
                event_name VARCHAR(120) NOT NULL,
                tenant_id VARCHAR(128) NOT NULL,
                payload TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                next_attempt_at DATETIME NOT NULL,
                last_error TEXT,
                dead_lettered_at DATETIME,
                created_at DATETIME NOT NULL,
                published_at DATETIME,
                claim_token VARCHAR(36),
                claimed_until DATETIME
            )
            """)
        )
        await connection.execute(
            text("""
            CREATE TABLE booking_audit (
                id VARCHAR(36) PRIMARY KEY,
                tenant_id VARCHAR(128) NOT NULL,
                booking_id VARCHAR(36) NOT NULL,
                resource_id VARCHAR(128) NOT NULL,
                actor_id VARCHAR(128) NOT NULL,
                action VARCHAR(64) NOT NULL,
                from_status VARCHAR(16),
                to_status VARCHAR(16) NOT NULL,
                created_at DATETIME NOT NULL
            )
            """)
        )
        await connection.execute(
            text("""
            INSERT INTO bookings
                (id, tenant_id, actor_id, resource_id, starts_at, ends_at,
                 status, idempotency_key, request_fingerprint)
            VALUES
                ('legacy-booking', 'tenant-north', 'employee-1', 'legacy-desk',
                 '2026-09-02 09:00:00', '2026-09-02 10:00:00', 'booked',
                 'legacy-key', 'legacy-fingerprint')
            """)
        )
    await engine.dispose()
    monkeypatch.setenv("WORKPLACE_BOOKINGS_DATABASE_URL", database_url)

    await migrate_bookings()
    await migrate_bookings()

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            columns = {
                row[1]
                for row in await connection.execute(text("PRAGMA table_info(bookings)"))
            }
            tables = {
                row[0]
                for row in await connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'table'")
                )
            }
            legacy = (
                await connection.execute(
                    text("""
                    SELECT series_id, occurrence_index
                    FROM bookings WHERE id = 'legacy-booking'
                    """)
                )
            ).one()
    finally:
        await engine.dispose()

    assert {"series_id", "occurrence_index"} <= columns
    assert {
        "booking_operations",
        "booking_series",
        "booking_cancellation_operations",
    } <= tables
    assert tuple(legacy) == (None, None)


@pytest.mark.asyncio
async def test_notifications_migration_adds_inbox_without_losing_existing_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _sqlite_url(tmp_path / "notifications.db")
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text("""
            CREATE TABLE notifications (
                id VARCHAR(36) PRIMARY KEY,
                tenant_id VARCHAR(128) NOT NULL,
                event_id VARCHAR(128) NOT NULL UNIQUE,
                message TEXT NOT NULL,
                created_at DATETIME NOT NULL
            )
            """)
        )
        await connection.execute(
            text("""
            INSERT INTO notifications
                (id, tenant_id, event_id, message, created_at)
            VALUES
                ('notification-1', 'tenant-north', 'legacy-event-1',
                 'Booking booking-1 created', '2026-09-02 09:00:00')
            """)
        )
    await engine.dispose()
    monkeypatch.setenv("WORKPLACE_NOTIFICATIONS_DATABASE_URL", database_url)

    await migrate_notifications()
    await migrate_notifications()

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            tables = {
                row[0]
                for row in await connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'table'")
                )
            }
            notification_count = await connection.scalar(
                text("SELECT count(*) FROM notifications")
            )
            inbox_columns = {
                row[1]: row
                for row in await connection.execute(
                    text("PRAGMA table_info(notification_inbox)")
                )
            }
    finally:
        await engine.dispose()

    assert "notification_inbox" in tables
    assert notification_count == 1
    assert {
        "event_id",
        "tenant_id",
        "event_name",
        "payload_fingerprint",
        "processed_at",
    } == inbox_columns.keys()
    assert inbox_columns["event_id"][5] == 1
