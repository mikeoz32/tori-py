"""Dedicated notifications schema migration job for the demo compose stack."""

from __future__ import annotations

import asyncio

from examples.nestpy.microservices_app.common.infrastructure import (
    database_url,
    migrate,
)
from examples.nestpy.microservices_app.notifications.app import Base

if __name__ == "__main__":
    asyncio.run(migrate(Base.metadata, database_url("notifications")))
