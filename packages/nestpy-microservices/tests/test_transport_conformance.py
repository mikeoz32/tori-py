from __future__ import annotations

import pytest
from nestpy_microservices.testing import assert_transport_conformance

from nestpy_microservices import (
    EventIdentity,
    InMemoryBroker,
    InMemoryClientTransport,
    InMemoryServerTransport,
    ServiceIdentity,
)


@pytest.mark.asyncio
async def test_inmemory_transport_conformance() -> None:
    service = ServiceIdentity("conformance", "inmemory", 1)
    event = EventIdentity(ServiceIdentity("conformance", "publisher", 1), "changed", 1)
    broker = InMemoryBroker(max_delivery_attempts=3)
    try:
        await assert_transport_conformance(
            InMemoryServerTransport(broker, service, prefetch=2),
            InMemoryClientTransport(broker),
            service=service,
            event=event,
            max_delivery_attempts=3,
            max_inflight_deliveries=2,
            timeout=2,
        )
    finally:
        await broker.close()
