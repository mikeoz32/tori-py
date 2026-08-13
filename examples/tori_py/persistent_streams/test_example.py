from __future__ import annotations

import pytest
from tori_py_persistent_streams_core import PublishOutcome

from examples.tori_py.persistent_streams.app import (
    DemoRunner,
    MemberProjection,
    create_application,
)


@pytest.mark.asyncio
async def test_documented_tori_py_persistent_streams_core_application() -> None:
    for _ in range(2):
        application = await create_application()

        try:
            await application.start()

            assert {receipt.outcome for receipt in DemoRunner.receipts} == {
                PublishOutcome.CONFIRMED
            }
            assert {item.payload.display_name for item in MemberProjection.handled} == {
                "Ada Lovelace",
                "Grace Hopper",
                "Alan Turing",
            }
            assert {item.partition for item in MemberProjection.handled} == {0, 1}
            assert all(item.offset >= 0 for item in MemberProjection.handled)
        finally:
            await application.shutdown()

        assert application.state.value == "stopped"
