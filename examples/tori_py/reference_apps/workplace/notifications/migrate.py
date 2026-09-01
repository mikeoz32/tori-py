from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from ..common.infrastructure import database_url
from .app import Base


async def migrate() -> None:
    engine = create_async_engine(database_url("notifications"))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
