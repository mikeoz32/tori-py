"""Dedicated catalog schema migration job for the demo compose stack."""

from __future__ import annotations

import asyncio

from examples.tori_py.microservices_app.catalog.app import Base
from examples.tori_py.microservices_app.common.infrastructure import (
    database_url,
    migrate,
)

if __name__ == "__main__":
    asyncio.run(migrate(Base.metadata, database_url("catalog")))
