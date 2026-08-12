from __future__ import annotations

import pytest
from persistent_streams import PublishOutcome

from examples.nestpy.persistent_streams.app import (
    DemoRunner,
    MemberProjection,
    create_application,
)


@pytest.mark.asyncio
async def test_documented_persistent_streams_application() -> None:
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
