from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest
from tori_py_persistent_streams_core import (
    AppendRequest,
    IncompatibleStreamError,
    InMemoryPersistentLog,
    InvalidPartitionError,
    PublishingConflictError,
    PublishOutcome,
    ResourceLimitError,
    RetentionGapError,
    StalePublishingIdError,
    StreamDefinition,
    StreamLimits,
    ValidationError,
)
from tori_py_persistent_streams_core.routing import Sha256PartitionRouter


class _InvalidRouter:
    identity = "invalid-v1"

    def __init__(self, result: object) -> None:
        self.result = result

    @property
    def compatibility_key(self) -> tuple[str, object]:
        return (self.identity, self.result)

    def route(self, partition_key: bytes, partition_count: int) -> int:
        return cast(Any, self.result)


class _MutableRouter:
    identity = "mutable-v1"

    def __init__(self, partition: int) -> None:
        self.partition = partition

    @property
    def compatibility_key(self) -> tuple[str, int]:
        return (self.identity, self.partition)

    def route(self, partition_key: bytes, partition_count: int) -> int:
        return self.partition


@pytest.mark.asyncio
async def test_sparse_partition_order_and_finite_reads() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(
        StreamDefinition("events", 1, StreamLimits(max_read_records=2))
    )
    requests = [AppendRequest(uuid4(), b"same", bytes([index])) for index in range(3)]
    await asyncio.gather(*(log.append("events", request) for request in requests))

    page = await log.read("events", 0, 0, 2)
    assert [record.offset for record in page.records] == [0, 2]
    assert page.bounds is not None
    assert page.bounds.end_offset == 6
    with pytest.raises(ResourceLimitError):
        await log.read("events", 0, 0, 3)


@pytest.mark.asyncio
async def test_named_producer_retry_conflict_stale_and_trim_independence() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))
    request = AppendRequest(uuid4(), b"key", b"one", producer_name="p", publishing_id=5)
    first = await log.append("events", request)
    retry = await log.append("events", request)
    assert first.outcome is PublishOutcome.CONFIRMED
    assert retry.outcome is PublishOutcome.DEDUPLICATED
    assert await log.trim("events", 0, 2) == 1
    assert (await log.append("events", request)).outcome is PublishOutcome.DEDUPLICATED

    with pytest.raises(PublishingConflictError):
        await log.append(
            "events",
            AppendRequest(
                uuid4(), b"key", b"other", producer_name="p", publishing_id=5
            ),
        )
    await log.append(
        "events",
        AppendRequest(uuid4(), b"key", b"new", producer_name="p", publishing_id=9),
    )
    with pytest.raises(StalePublishingIdError):
        await log.append("events", request)
    with pytest.raises(RetentionGapError):
        await log.read("events", 0, 0, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [True, 0.5, -1, 2])
async def test_invalid_router_result_is_rejected_before_append(result: object) -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(
        StreamDefinition("events", 2, router=_InvalidRouter(result))
    )

    with pytest.raises(InvalidPartitionError):
        await log.append("events", AppendRequest(uuid4(), b"key"))

    assert (await log.bounds("events", 0)).end_offset == 0
    assert (await log.bounds("events", 1)).end_offset == 0


@pytest.mark.asyncio
async def test_declaration_freezes_router_against_caller_mutation() -> None:
    log = InMemoryPersistentLog()
    definition = StreamDefinition("events", 2, router=_MutableRouter(0))
    await log.declare_stream(definition)

    cast(_MutableRouter, definition.router).partition = 1

    receipt = await log.append("events", AppendRequest(uuid4(), b"key"))
    assert receipt.partition == 0


@pytest.mark.asyncio
async def test_same_router_identity_with_different_config_is_incompatible() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 2, router=_MutableRouter(0)))

    with pytest.raises(IncompatibleStreamError):
        await log.declare_stream(
            StreamDefinition("events", 2, router=_MutableRouter(1))
        )


@pytest.mark.parametrize("partition_count", [True, 1.5, "2", 0])
def test_default_router_rejects_invalid_partition_count(
    partition_count: object,
) -> None:
    with pytest.raises(ValidationError):
        Sha256PartitionRouter().route(b"key", cast(int, partition_count))
