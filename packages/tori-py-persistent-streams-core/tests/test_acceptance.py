from __future__ import annotations

from uuid import uuid4

import pytest
from tori_py_persistent_streams_core import (
    AppendRequest,
    Beginning,
    CheckpointPersistenceError,
    CheckpointStrategy,
    ConsumerRunner,
    ExternalCheckpointStrategy,
    InMemoryCheckpointStore,
    InMemoryPersistentLog,
    PoisonRecordError,
    RetentionGapError,
    StreamDefinition,
    Subscription,
)


class _FailOnceCheckpointStore(InMemoryCheckpointStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail = True

    async def save(self, key, expected, cursor, owner) -> None:
        if self.fail:
            self.fail = False
            raise OSError("checkpoint unavailable")
        await super().save(key, expected, cursor, owner)


@pytest.mark.asyncio
async def test_multi_partition_poison_and_external_duplicate_window() -> None:
    log = InMemoryPersistentLog()
    definition = StreamDefinition("events", 3)
    await log.declare_stream(definition)
    keys: dict[int, bytes] = {}
    candidate = 0
    while len(keys) < 3:
        key = f"key-{candidate}".encode()
        keys.setdefault(definition.router.route(key, 3), key)
        candidate += 1
    for partition in range(3):
        await log.append(
            "events", AppendRequest(uuid4(), keys[partition], bytes([partition]))
        )

    leases = [
        await log.acquire(
            Subscription("events", "projection", f"owner-{partition}", Beginning()),
            partition,
            strategy=CheckpointStrategy.BROKER_MANAGED,
        )
        for partition in range(3)
    ]

    async def fail(_record) -> None:
        raise RuntimeError("poison")

    with pytest.raises(PoisonRecordError):
        await ConsumerRunner().run_once(leases[0], fail)
    progressed: list[int] = []

    async def handle(record) -> None:
        progressed.append(record.partition)

    assert await ConsumerRunner().run_once(leases[1], handle) == 1
    assert progressed == [1]
    replacement = await log.acquire(
        Subscription("events", "projection", "replacement", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
        transfer=True,
    )
    assert await ConsumerRunner().run_once(replacement, handle) == 1

    store = _FailOnceCheckpointStore()
    strategy = ExternalCheckpointStrategy("acceptance-checkpoints", store)
    external = await log.acquire(
        Subscription("events", "external", "one", Beginning()),
        2,
        strategy=strategy,
    )
    effects: list[bytes] = []

    async def effect(record) -> None:
        effects.append(record.payload)

    with pytest.raises(CheckpointPersistenceError):
        await ConsumerRunner().run_once(external, effect)
    retry = await log.acquire(
        Subscription("events", "external", "two", Beginning()),
        2,
        strategy=strategy,
        transfer=True,
    )
    assert await ConsumerRunner().run_once(retry, effect) == 1
    assert effects == [b"\x02", b"\x02"]


@pytest.mark.asyncio
async def test_stale_successful_checkpoint_reports_retention_gap() -> None:
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("events", 1))
    await log.append("events", AppendRequest(uuid4(), b"key", b"first"))
    lease = await log.acquire(
        Subscription("events", "group", "one", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )

    async def handle(_record) -> None:
        pass

    await ConsumerRunner().run_once(lease, handle)
    await lease.release()
    await log.trim("events", 0, 2)
    restarted = await log.acquire(
        Subscription("events", "group", "two", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )
    with pytest.raises(RetentionGapError) as caught:
        await restarted.next_record()
    assert caught.value.group == "group"
