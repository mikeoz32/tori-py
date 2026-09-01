"""Focused domain, event-store, and projection invariant tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from tori_py_cqrs_event_sourcing import CommandSynchronization
from tori_py_cqrs_event_sourcing_core import (
    AppendEvent,
    CommitResult,
    EncodedEvent,
    EventCodecError,
    EventMetadata,
    EventSourcingUnitOfWork,
    InMemoryEventStore,
    StoredEvent,
    StreamId,
)
from tori_py_persistent_streams import StreamPublisher
from tori_py_persistent_streams_core import PublishOutcome, PublishReceipt

from .audit.app import AuditEventConflict, TaskAuditLog
from .projection.state import ProjectionCorruption, TaskProjectionState
from .streams import TaskEventRecordV1
from .tasks.domain import (
    TaskAggregate,
    TaskCreated,
    TaskRenamed,
    TaskTitleInvalid,
    normalize_title,
)
from .tasks.handlers import CreateTaskHandler, RenameTaskHandler
from .tasks.messages import CreateTask, RenameTask
from .tasks.relay import (
    RelayGate,
    RelayPublicationError,
    RelayUnavailable,
    TaskEventRelay,
)
from .tasks.repository import TaskRepository
from .tasks.schemas import (
    TASK_CREATED_ALIAS,
    TASK_RENAMED_ALIAS,
    TASK_SCHEMAS,
)
from .tasks.state import TaskIdSequence


def test_task_aggregate_normalizes_titles_and_same_rename_is_a_noop() -> None:
    for title in ("   ", "x" * 121, "\ud800"):
        with pytest.raises(TaskTitleInvalid):
            normalize_title(title)

    aggregate = TaskAggregate(7)
    aggregate.create("  Write Part 4  ")
    assert aggregate.title == "Write Part 4"
    assert len(aggregate.pending_events) == 1
    created = aggregate.pending_events[0]
    assert created.event == TaskCreated(7, "Write Part 4")
    assert created.metadata.event_id
    assert created.metadata.occurred_at.tzinfo is not None

    aggregate.rename(" Write Part 4 ")
    assert len(aggregate.pending_events) == 1


@pytest.mark.parametrize(
    "value",
    (
        {"task_id": 1, "title": "Title", "unexpected": True},
        {"task_id": 1},
        {"task_id": 1, "title": " Title"},
        {"task_id": 1, "title": "Title "},
        {"task_id": 1, "title": "   "},
        {"task_id": 1, "title": "x" * 121},
        {"task_id": 1, "title": "\ud800"},
    ),
)
def test_persisted_schema_rejects_non_exact_or_invalid_payloads(
    value: dict[str, object],
) -> None:
    payload = json.dumps(value, ensure_ascii=True).encode("ascii")
    with pytest.raises(EventCodecError):
        TASK_SCHEMAS.decode(_stored(payload))


def test_persisted_schema_accepts_exact_normalized_utf8_title() -> None:
    payload = json.dumps(
        {"task_id": 1, "title": "Caf\u00e9"},
        ensure_ascii=False,
    ).encode("utf-8")
    decoded = TASK_SCHEMAS.decode(_stored(payload))
    assert decoded.event == TaskCreated(1, "Caf\u00e9")


@pytest.mark.asyncio
async def test_repository_persists_stable_aliases_versions_and_metadata() -> None:
    store = InMemoryEventStore()

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repository = _repository(unit_of_work)
        aggregate = TaskAggregate(1)
        aggregate.create("First title")
        pending_id = aggregate.pending_events[0].metadata.event_id
        repository.save(aggregate)
        created = await unit_of_work.commit()

    assert aggregate.version == 1
    assert created.events[0].event_id == pending_id
    assert created.events[0].event.encoded.event_type == TASK_CREATED_ALIAS
    assert created.events[0].event.encoded.schema_version == 1

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repository = _repository(unit_of_work)
        loaded = await repository.get(1)
        loaded.rename("First title")
        repository.save(loaded)
        no_op = await unit_of_work.commit()

    assert no_op.events == ()

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repository = _repository(unit_of_work)
        loaded = await repository.get(1)
        loaded.rename("  Renamed title ")
        renamed_id = loaded.pending_events[0].metadata.event_id
        repository.save(loaded)
        renamed = await unit_of_work.commit()

    events = await store.read_all(limit=10)
    assert [event.stream_version for event in events] == [1, 2]
    assert [event.global_position for event in events] == [1, 2]
    assert [event.event.encoded.event_type for event in events] == [
        TASK_CREATED_ALIAS,
        TASK_RENAMED_ALIAS,
    ]
    assert renamed.events[0].event_id == renamed_id
    assert TASK_SCHEMAS.decode(events[0]).event == TaskCreated(1, "First title")
    assert TASK_SCHEMAS.decode(events[1]).event == TaskRenamed(1, "Renamed title")


@pytest.mark.asyncio
async def test_projection_is_duplicate_safe_and_rejects_version_gaps() -> None:
    state = TaskProjectionState()
    occurred_at = datetime.now(UTC)
    created = TaskEventRecordV1(
        uuid4(),
        "task-created",
        1,
        "First title",
        1,
        1,
        occurred_at,
    )
    await state.apply(created)
    await state.apply(created)

    assert state.deliveries == 2
    assert state.event_count == 1
    assert state.get(1).title == "First title"

    gap = TaskEventRecordV1(
        uuid4(),
        "task-renamed",
        1,
        "Skipped version",
        3,
        2,
        occurred_at,
    )
    with pytest.raises(ProjectionCorruption):
        await state.apply(gap)
    assert state.unavailable


@pytest.mark.asyncio
async def test_audit_accepts_exact_duplicates_and_rejects_conflicting_ids() -> None:
    audit = TaskAuditLog()
    event = _task_record()
    await audit.record(event)
    await audit.record(event)

    conflicting = TaskEventRecordV1(
        event.event_id,
        event.kind,
        event.task_id,
        "Conflicting title",
        event.aggregate_version,
        event.source_global_position,
        event.occurred_at,
    )
    with pytest.raises(AuditEventConflict):
        await audit.record(conflicting)

    assert audit.deliveries == 3
    assert audit.entries == (event,)


@pytest.mark.asyncio
async def test_indeterminate_relay_publication_degrades_without_resend() -> None:
    store = InMemoryEventStore()
    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repository = _repository(unit_of_work)
        aggregate = TaskAggregate(1)
        aggregate.create("Relay failure")
        repository.save(aggregate)
        await unit_of_work.commit()

    publisher = _IndeterminatePublisher()
    relay = TaskEventRelay(
        store,
        TASK_SCHEMAS,
        cast(StreamPublisher, publisher),
        RelayGate(),
    )
    await relay.on_application_bootstrap()
    try:
        with pytest.raises(RelayPublicationError):
            await relay.wait_for_checkpoint(1, timeout=1)
        with pytest.raises(RelayUnavailable):
            relay.require_available()

        relay.after_commit(CommitResult(()))
        with pytest.raises(RelayPublicationError):
            await relay.wait_for_checkpoint(1, timeout=1)
        assert publisher.calls == 1
    finally:
        await relay.close()


@pytest.mark.asyncio
async def test_degraded_relay_rejects_commands_before_state_access() -> None:
    relay = cast(TaskEventRelay, _UnavailableRelay())
    repository = _UnusedRepository()
    synchronization = cast(CommandSynchronization, _UnusedSynchronization())
    ids = TaskIdSequence()
    create = CreateTaskHandler(
        cast(TaskRepository, repository),
        ids,
        synchronization,
        relay,
    )
    rename = RenameTaskHandler(
        cast(TaskRepository, repository),
        synchronization,
        relay,
    )

    with pytest.raises(RelayUnavailable):
        await create.handle(CreateTask("Not allocated"))
    with pytest.raises(RelayUnavailable):
        await rename.handle(RenameTask(99, "Not loaded"))

    assert ids.next() == 1
    assert repository.loads == 0
    assert repository.saves == 0


def _repository(unit_of_work: EventSourcingUnitOfWork) -> TaskRepository:
    return TaskRepository(
        unit_of_work,
        category="task",
        aggregate_factory=TaskAggregate,
        aggregate_type=TaskAggregate,
        id_encoder=str,
        schemas=TASK_SCHEMAS,
    )


def _stored(payload: bytes) -> StoredEvent:
    return StoredEvent(
        StreamId("task", "1"),
        1,
        1,
        AppendEvent(
            EncodedEvent(TASK_CREATED_ALIAS, 1, payload),
            EventMetadata(uuid4(), datetime.now(UTC)),
        ),
    )


def _task_record() -> TaskEventRecordV1:
    return TaskEventRecordV1(
        uuid4(),
        "task-created",
        1,
        "Title",
        1,
        1,
        datetime.now(UTC),
    )


class _IndeterminatePublisher:
    def __init__(self) -> None:
        self.calls = 0

    async def publish(
        self,
        stream: str,
        payload: object,
        *,
        record_id: UUID | None = None,
        headers: Mapping[str, bytes] | None = None,
    ) -> PublishReceipt:
        del stream, payload, headers
        assert record_id is not None
        self.calls += 1
        return PublishReceipt(record_id, 0, PublishOutcome.INDETERMINATE)


class _UnavailableRelay:
    def require_available(self) -> None:
        raise RelayUnavailable("relay unavailable")

    def after_commit(self, result: CommitResult) -> None:
        del result


class _UnusedRepository:
    def __init__(self) -> None:
        self.loads = 0
        self.saves = 0

    async def get(self, task_id: int) -> TaskAggregate:
        self.loads += 1
        return TaskAggregate(task_id)

    def save(self, aggregate: TaskAggregate) -> None:
        del aggregate
        self.saves += 1


class _UnusedSynchronization:
    def after_commit(self, callback: object) -> None:
        del callback

    def after_confirmed_non_commit(self, callback: object) -> None:
        del callback

    def after_indeterminate(self, callback: object) -> None:
        del callback
