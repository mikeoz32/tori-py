import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from tori_py_cqrs_event_sourcing_core import (
    AppendEvent,
    DuplicateEventIdError,
    DuplicateStreamAppendError,
    EncodedEvent,
    EventMetadata,
    EventSourcingLimits,
    EventStore,
    EventStoreTransaction,
    EventStoreTransactionError,
    InMemoryEventStore,
    OptimisticConcurrencyError,
    ResourceLimitError,
    StreamId,
)


def append_event(
    value: int,
    *,
    payload: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> AppendEvent:
    return AppendEvent(
        EncodedEvent("profile.changed", 1, payload or str(value).encode()),
        EventMetadata(
            event_id=UUID(int=value),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            headers={} if headers is None else headers,
        ),
    )


async def commit(
    store: EventStore,
    stream: StreamId,
    expected_version: int,
    *events: AppendEvent,
):
    async with store.transaction() as transaction:
        transaction.append(
            stream,
            expected_version=expected_version,
            events=tuple(events),
        )
        return await transaction.commit()


def test_store_protocols_are_runtime_checkable() -> None:
    store = InMemoryEventStore()
    assert isinstance(store, EventStore)
    assert isinstance(store.transaction(), EventStoreTransaction)


@pytest.mark.asyncio
async def test_commit_assigns_contiguous_stream_and_global_positions(
    event_store_factory,
) -> None:
    store = event_store_factory(None)
    first = StreamId("profile", "1")
    second = StreamId("profile", "2")

    async with store.transaction() as transaction:
        transaction.append(first, expected_version=0, events=(append_event(1),))
        transaction.append(
            second,
            expected_version=0,
            events=(append_event(2), append_event(3)),
        )
        result = await transaction.commit()

    assert [event.global_position for event in result.events] == [1, 2, 3]
    assert [event.stream_version for event in result.events] == [1, 1, 2]
    assert result.final_version(first) == 1
    assert result.final_version(second) == 2
    assert await store.read_stream(first, limit=10) == (result.events[0],)
    assert await store.read_all(limit=2) == result.events[:2]
    assert await store.read_all(after_position=2, limit=2) == result.events[2:]


@pytest.mark.asyncio
async def test_missing_stream_and_finite_version_pagination(
    event_store_factory,
) -> None:
    store = event_store_factory(EventSourcingLimits(read_page_size=2))
    stream = StreamId("profile", "1")
    assert await store.read_stream(stream, limit=1) == ()
    await commit(store, stream, 0, append_event(1), append_event(2), append_event(3))

    assert [
        event.stream_version for event in await store.read_stream(stream, limit=2)
    ] == [1, 2]
    assert [
        event.stream_version
        for event in await store.read_stream(stream, after_version=2, limit=2)
    ] == [3]
    with pytest.raises(ResourceLimitError, match="cannot exceed"):
        await store.read_stream(stream, limit=3)


@pytest.mark.asyncio
async def test_transaction_reads_repeatable_snapshot_without_staged_events(
    event_store_factory,
) -> None:
    store = event_store_factory(None)
    stream = StreamId("profile", "1")

    async with store.transaction() as snapshot:
        assert await snapshot.read_stream(stream, limit=10) == ()
        snapshot.append(stream, expected_version=0, events=(append_event(1),))
        assert await snapshot.read_stream(stream, limit=10) == ()

        await commit(store, StreamId("profile", "2"), 0, append_event(2))
        assert await snapshot.read_stream(StreamId("profile", "2"), limit=10) == ()
        await snapshot.commit()


@pytest.mark.asyncio
async def test_multi_stream_commit_validates_every_stream_before_mutation(
    event_store_factory,
) -> None:
    store = event_store_factory(None)
    existing = StreamId("profile", "existing")
    new = StreamId("profile", "new")
    await commit(store, existing, 0, append_event(1))

    async with store.transaction() as transaction:
        transaction.append(new, expected_version=0, events=(append_event(2),))
        transaction.append(existing, expected_version=0, events=(append_event(3),))
        with pytest.raises(OptimisticConcurrencyError) as failure:
            await transaction.commit()

    assert failure.value.stream_id == existing
    assert failure.value.expected_version == 0
    assert failure.value.actual_version == 1
    assert await store.read_stream(new, limit=10) == ()
    assert len(await store.read_all(limit=10)) == 1


@pytest.mark.asyncio
async def test_concurrent_expected_version_writers_have_one_winner(
    event_store_factory,
) -> None:
    store = event_store_factory(None)
    stream = StreamId("profile", "1")
    ready = asyncio.Barrier(2)

    async def writer(value: int):
        async with store.transaction() as transaction:
            transaction.append(
                stream,
                expected_version=0,
                events=(append_event(value),),
            )
            await ready.wait()
            return await transaction.commit()

    results = await asyncio.gather(writer(1), writer(2), return_exceptions=True)

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(failures) == 1
    assert isinstance(failures[0], OptimisticConcurrencyError)
    assert len(await store.read_stream(stream, limit=10)) == 1


@pytest.mark.asyncio
async def test_duplicate_stream_and_event_ids_are_rejected(
    event_store_factory,
) -> None:
    store = event_store_factory(None)
    first = StreamId("profile", "1")
    second = StreamId("profile", "2")
    event = append_event(1)

    async with store.transaction() as transaction:
        with pytest.raises(DuplicateEventIdError):
            transaction.append(
                StreamId("profile", "same-batch"),
                expected_version=0,
                events=[event, event],
            )
        transaction.append(first, expected_version=0, events=(event,))
        with pytest.raises(DuplicateStreamAppendError):
            transaction.append(first, expected_version=0, events=(append_event(2),))
        with pytest.raises(DuplicateEventIdError):
            transaction.append(second, expected_version=0, events=(event,))

    await commit(store, first, 0, event)
    async with store.transaction() as transaction:
        transaction.append(second, expected_version=0, events=(event,))
        with pytest.raises(DuplicateEventIdError):
            await transaction.commit()


@pytest.mark.asyncio
async def test_context_exit_rolls_back_and_closed_transaction_rejects_use(
    event_store_factory,
) -> None:
    store = event_store_factory(None)
    stream = StreamId("profile", "1")
    transaction = store.transaction()
    async with transaction:
        transaction.append(stream, expected_version=0, events=(append_event(1),))

    assert await store.read_stream(stream, limit=10) == ()
    await transaction.rollback()
    with pytest.raises(EventStoreTransactionError, match="rolled_back"):
        await transaction.commit()


@pytest.mark.asyncio
async def test_store_enforces_batch_transaction_and_payload_limits(
    event_store_factory,
) -> None:
    limits = EventSourcingLimits(
        max_payload_bytes=2,
        max_events_per_append=1,
        max_events_per_transaction=1,
        max_transaction_bytes=1,
    )
    store = event_store_factory(limits)
    async with store.transaction() as transaction:
        with pytest.raises(ResourceLimitError, match="append event count"):
            transaction.append(
                StreamId("profile", "1"),
                expected_version=0,
                events=(append_event(1), append_event(2)),
            )
        with pytest.raises(ResourceLimitError, match="payload byte"):
            transaction.append(
                StreamId("profile", "2"),
                expected_version=0,
                events=(append_event(2, payload=b"abc"),),
            )
        with pytest.raises(ResourceLimitError, match="transaction byte"):
            transaction.append(
                StreamId("profile", "3"),
                expected_version=0,
                events=(append_event(3, payload=b"ab"),),
            )


@pytest.mark.asyncio
async def test_store_enforces_accumulated_event_and_header_byte_limits(
    event_store_factory,
) -> None:
    event_limits = EventSourcingLimits(
        max_events_per_append=2,
        max_events_per_transaction=2,
    )
    store = event_store_factory(event_limits)
    async with store.transaction() as transaction:
        transaction.append(
            StreamId("profile", "1"),
            expected_version=0,
            events=[append_event(1)],
        )
        with pytest.raises(ResourceLimitError, match="transaction event count"):
            transaction.append(
                StreamId("profile", "2"),
                expected_version=0,
                events=[append_event(2), append_event(3)],
            )

    byte_limits = EventSourcingLimits(
        max_payload_bytes=10,
        max_header_value_bytes=10,
        max_transaction_bytes=20,
    )
    store = event_store_factory(byte_limits)
    async with store.transaction() as transaction:
        with pytest.raises(ResourceLimitError, match="transaction byte"):
            transaction.append(
                StreamId("profile", "headers"),
                expected_version=0,
                events=[append_event(4, payload=b"x", headers={"key": "1234567890"})],
            )


@pytest.mark.asyncio
async def test_cancelled_lock_wait_has_known_rollback_outcome() -> None:
    store = InMemoryEventStore()
    stream = StreamId("profile", "1")
    transaction = store.transaction()
    await transaction.__aenter__()
    transaction.append(stream, expected_version=0, events=(append_event(1),))

    await store._lock.acquire()
    task = asyncio.create_task(transaction.commit())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    store._lock.release()
    await transaction.__aexit__(None, None, None)

    assert await store.read_stream(stream, limit=10) == ()


@pytest.mark.asyncio
async def test_state_build_failure_cannot_publish_partial_store_state(
    monkeypatch,
) -> None:
    store = InMemoryEventStore()
    existing = StreamId("profile", "existing")
    await commit(store, existing, 0, append_event(1))
    before = await store.read_all(limit=10)
    transaction = store.transaction()
    await transaction.__aenter__()
    transaction.append(
        StreamId("profile", "new"),
        expected_version=0,
        events=[append_event(2)],
    )

    def fail_state_build(committed):
        del committed
        raise MemoryError("simulated allocation failure")

    monkeypatch.setattr(transaction, "_build_store_state", fail_state_build)
    with pytest.raises(MemoryError, match="allocation"):
        await transaction.commit()
    await transaction.__aexit__(None, None, None)

    assert await store.read_all(limit=10) == before
    assert await store.read_stream(StreamId("profile", "new"), limit=10) == ()


@pytest.mark.asyncio
async def test_committing_transaction_rejects_competing_operations() -> None:
    store = InMemoryEventStore()
    stream = StreamId("profile", "1")
    transaction = store.transaction()
    await transaction.__aenter__()
    transaction.append(stream, expected_version=0, events=[append_event(1)])

    await store._lock.acquire()
    committing = asyncio.create_task(transaction.commit())
    await asyncio.sleep(0)
    with pytest.raises(EventStoreTransactionError, match="committing"):
        await transaction.read_stream(stream, limit=10)
    with pytest.raises(EventStoreTransactionError, match="committing"):
        transaction.append(
            StreamId("profile", "2"),
            expected_version=0,
            events=[append_event(2)],
        )
    with pytest.raises(EventStoreTransactionError, match="committing"):
        await transaction.rollback()
    with pytest.raises(EventStoreTransactionError, match="committing"):
        await transaction.commit()
    store._lock.release()
    result = await committing
    await transaction.__aexit__(None, None, None)

    assert len(result.events) == 1


@pytest.mark.asyncio
async def test_entering_transaction_rejects_second_entry() -> None:
    store = InMemoryEventStore()
    transaction = store.transaction()
    await store._lock.acquire()
    entering = asyncio.create_task(transaction.__aenter__())
    await asyncio.sleep(0)
    with pytest.raises(EventStoreTransactionError, match="entering"):
        await transaction.__aenter__()
    store._lock.release()
    assert await entering is transaction
    await transaction.rollback()
    await transaction.__aexit__(None, None, None)
