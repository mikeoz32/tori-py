from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ..common.infrastructure import database_url
from .app import Base


async def migrate() -> None:
    engine = create_async_engine(database_url("spaces"))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            if connection.dialect.name == "postgresql":
                await connection.execute(
                    text("""
                    ALTER TABLE resources
                      ADD COLUMN IF NOT EXISTS equipment_json
                        TEXT NOT NULL DEFAULT '[]',
                      ADD COLUMN IF NOT EXISTS capacity INTEGER NOT NULL DEFAULT 1,
                      ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT true;
                    """)
                )
            elif connection.dialect.name == "sqlite":
                columns = {
                    row[1]
                    for row in (
                        await connection.execute(text("PRAGMA table_info(resources)"))
                    )
                }
                if "equipment_json" not in columns:
                    await connection.execute(
                        text(
                            "ALTER TABLE resources ADD COLUMN "
                            "equipment_json TEXT NOT NULL DEFAULT '[]'"
                        )
                    )
                if "capacity" not in columns:
                    await connection.execute(
                        text(
                            "ALTER TABLE resources ADD COLUMN "
                            "capacity INTEGER NOT NULL DEFAULT 1"
                        )
                    )
                if "active" not in columns:
                    await connection.execute(
                        text(
                            "ALTER TABLE resources ADD COLUMN "
                            "active BOOLEAN NOT NULL DEFAULT 1"
                        )
                    )
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
                                (id, tenant_id, office_id, floor_id, name, kind, x, y,
                                 equipment_json, capacity, active)
                            VALUES
                                (:id, :tenant_id, 'building-n', 'level-03',
                                 :name, :kind, :x, :y, :equipment, :capacity, true)
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
                            "equipment": (
                                '["monitor", "power"]'
                                if kind == "desk"
                                else '["screen", "whiteboard"]'
                            ),
                            "capacity": 1 if kind == "desk" else 4,
                        },
                    )
                await connection.execute(
                    text(
                        """
                        INSERT INTO office_policies
                            (id, tenant_id, office_id, time_zone, opens_at_minute,
                             closes_at_minute, weekdays_json)
                        VALUES
                            (:id, :tenant_id, 'building-n', 'Europe/London',
                             480, 1080, '[0, 1, 2, 3, 4]')
                        ON CONFLICT (tenant_id, office_id) DO NOTHING
                        """
                    ),
                    {"id": f"{prefix}-building-n", "tenant_id": tenant},
                )
            resources = await connection.execute(
                text("SELECT tenant_id, id, equipment_json FROM resources")
            )
            for tenant_id, resource_id, equipment_json in resources:
                for name in json.loads(equipment_json):
                    await connection.execute(
                        text(
                            """
                            INSERT INTO resource_equipment
                                (tenant_id, resource_id, name)
                            VALUES (:tenant_id, :resource_id, :name)
                            ON CONFLICT (tenant_id, resource_id, name) DO NOTHING
                            """
                        ),
                        {
                            "tenant_id": tenant_id,
                            "resource_id": resource_id,
                            "name": name,
                        },
                    )
            offices = await connection.execute(
                text("SELECT DISTINCT tenant_id, office_id FROM resources")
            )
            for tenant_id, office_id in offices:
                await connection.execute(
                    text(
                        """
                        INSERT INTO office_policies
                            (id, tenant_id, office_id, time_zone, opens_at_minute,
                             closes_at_minute, weekdays_json)
                        VALUES
                            (:id, :tenant_id, :office_id, 'UTC', 0, 1439,
                             '[0, 1, 2, 3, 4, 5, 6]')
                        ON CONFLICT (tenant_id, office_id) DO NOTHING
                        """
                    ),
                    {
                        "id": str(uuid4()),
                        "tenant_id": tenant_id,
                        "office_id": office_id,
                    },
                )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
