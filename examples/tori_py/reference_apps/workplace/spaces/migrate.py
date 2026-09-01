from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ..common.infrastructure import database_url
from .app import Base


async def migrate() -> None:
    engine = create_async_engine(database_url("spaces"))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            for tenant, prefix in (
                ("tenant-north", "north"),
                ("tenant-south", "south"),
            ):
                for suffix, name, kind, x, y in (
                    ("desk-17", "Desk 17", "desk", 160, 580),
                    ("desk-18", "Desk 18", "desk", 280, 580),
                    ("desk-19", "Desk 19", "desk", 400, 580),
                    ("desk-20", "Desk 20", "desk", 520, 580),
                    ("booth-a", "Focus booth A", "room", 730, 580),
                    ("booth-b", "Focus booth B", "room", 840, 580),
                    ("meet-03", "Meet 03", "room", 710, 240),
                ):
                    await connection.execute(
                        text(
                            """
                            INSERT INTO resources
                                (id, tenant_id, office_id, floor_id, name, kind, x, y)
                            VALUES
                                (:id, :tenant_id, 'building-n', 'level-03',
                                 :name, :kind, :x, :y)
                            ON CONFLICT (id) DO NOTHING
                            """
                        ),
                        {
                            "id": f"{prefix}-{suffix}",
                            "tenant_id": tenant,
                            "name": name,
                            "kind": kind,
                            "x": x,
                            "y": y,
                        },
                    )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
