"""Bookings schema migration, including PostgreSQL-only overlap protection."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ..common.infrastructure import database_url
from .app import Base


async def migrate() -> None:
    engine = create_async_engine(database_url("bookings"))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            if connection.dialect.name == "postgresql":
                await connection.execute(
                    text("CREATE EXTENSION IF NOT EXISTS btree_gist")
                )
                await connection.execute(
                    text("""
                    ALTER TABLE bookings
                      ADD COLUMN IF NOT EXISTS series_id VARCHAR(36),
                      ADD COLUMN IF NOT EXISTS occurrence_index INTEGER;
                    """)
                )
                await connection.execute(
                    text("""
                    ALTER TABLE outbox
                      ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(128),
                      ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                      ADD COLUMN IF NOT EXISTS last_error TEXT,
                      ADD COLUMN IF NOT EXISTS dead_lettered_at TIMESTAMPTZ,
                      ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                      ADD COLUMN IF NOT EXISTS claim_token VARCHAR(36),
                      ADD COLUMN IF NOT EXISTS claimed_until TIMESTAMPTZ;
                    """)
                )
                await connection.execute(
                    text("""
                    UPDATE outbox
                    SET tenant_id = payload::jsonb ->> 'tenant_id'
                    WHERE tenant_id IS NULL;
                    """)
                )
                await connection.execute(
                    text("""
                    DO $$ BEGIN
                      IF EXISTS (SELECT 1 FROM outbox WHERE tenant_id IS NULL) THEN
                        RAISE EXCEPTION 'cannot backfill outbox tenant_id from payload';
                      END IF;
                      ALTER TABLE outbox ALTER COLUMN tenant_id SET NOT NULL;
                    END $$;
                    """)
                )
                await connection.execute(
                    text("""
                    CREATE OR REPLACE FUNCTION prevent_booking_audit_mutation()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN
                      RAISE EXCEPTION 'booking audit rows are immutable';
                    END $$;
                    """)
                )
                await connection.execute(
                    text("""
                    DROP TRIGGER IF EXISTS booking_audit_immutable ON booking_audit;
                    """)
                )
                await connection.execute(
                    text("""
                    CREATE TRIGGER booking_audit_immutable
                    BEFORE UPDATE OR DELETE ON booking_audit
                    FOR EACH ROW EXECUTE FUNCTION prevent_booking_audit_mutation();
                    """)
                )
                await connection.execute(
                    text("""
                    DO $$ BEGIN
                      IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'bookings_no_overlap'
                          AND conrelid = 'bookings'::regclass
                      ) THEN
                        ALTER TABLE bookings ADD CONSTRAINT bookings_no_overlap
                        EXCLUDE USING gist (tenant_id WITH =, resource_id WITH =,
                        tstzrange(starts_at, ends_at, '[)') WITH &&)
                        WHERE (status IN ('booked', 'checked_in'));
                      END IF;
                    END $$;
                """)
                )
            elif connection.dialect.name == "sqlite":
                booking_columns = {
                    row[1]
                    for row in (
                        await connection.execute(text("PRAGMA table_info(bookings)"))
                    )
                }
                if "series_id" not in booking_columns:
                    await connection.execute(
                        text("ALTER TABLE bookings ADD COLUMN series_id VARCHAR(36)")
                    )
                if "occurrence_index" not in booking_columns:
                    await connection.execute(
                        text("ALTER TABLE bookings ADD COLUMN occurrence_index INTEGER")
                    )
                columns = {
                    row[1]
                    for row in (
                        await connection.execute(text("PRAGMA table_info(outbox)"))
                    )
                }
                if "claim_token" not in columns:
                    await connection.execute(
                        text("ALTER TABLE outbox ADD COLUMN claim_token VARCHAR(36)")
                    )
                if "claimed_until" not in columns:
                    await connection.execute(
                        text("ALTER TABLE outbox ADD COLUMN claimed_until DATETIME")
                    )
                await connection.execute(
                    text("""
                    CREATE TRIGGER IF NOT EXISTS booking_audit_immutable_update
                    BEFORE UPDATE ON booking_audit
                    BEGIN
                      SELECT RAISE(ABORT, 'booking audit rows are immutable');
                    END;
                    """)
                )
                await connection.execute(
                    text("""
                    CREATE TRIGGER IF NOT EXISTS booking_audit_immutable_delete
                    BEFORE DELETE ON booking_audit
                    BEGIN
                      SELECT RAISE(ABORT, 'booking audit rows are immutable');
                    END;
                    """)
                )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
