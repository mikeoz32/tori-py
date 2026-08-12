from __future__ import annotations

import pytest
from persistent_streams import InMemoryPersistentLog
from persistent_streams.testing import run_conformance_suite


@pytest.mark.asyncio
async def test_inmemory_passes_public_conformance_helper() -> None:
    async def factory() -> InMemoryPersistentLog:
        return InMemoryPersistentLog()

    await run_conformance_suite(factory)
