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
                    DO $$ BEGIN
                      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bookings_no_overlap') THEN
                        ALTER TABLE bookings ADD CONSTRAINT bookings_no_overlap
                        EXCLUDE USING gist (tenant_id WITH =, resource_id WITH =,
                        tstzrange(starts_at, ends_at, '[)') WITH &&)
                        WHERE (status IN ('booked', 'checked_in'));
                      END IF;
                    END $$;
                """)
                )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
