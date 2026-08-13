from __future__ import annotations

import pytest
from tori_py_persistent_streams_core import InMemoryPersistentLog
from tori_py_persistent_streams_core.testing import run_conformance_suite


@pytest.mark.asyncio
async def test_inmemory_passes_public_conformance_helper() -> None:
    async def factory() -> InMemoryPersistentLog:
        return InMemoryPersistentLog()

    await run_conformance_suite(factory)
