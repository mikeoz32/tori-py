"""Dedicated orders schema migration job for the demo compose stack."""

from __future__ import annotations

import asyncio

from examples.tori_py.microservices_app.common.infrastructure import (
    database_url,
    migrate,
)
from examples.tori_py.microservices_app.orders.app import Base

if __name__ == "__main__":
    asyncio.run(migrate(Base.metadata, database_url("orders")))
