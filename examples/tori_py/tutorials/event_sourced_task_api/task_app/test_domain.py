"""Focused domain, event-store, and projection invariant tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
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
from .tasks.publisher import (
    TaskEventPublicationError,
    TaskEventPublisher,
)
from .tasks.repository import TaskRepository
from .tasks.schemas import (
    TASK_CREATED_ALIAS,
    TASK_RENAMED_ALIAS,
    TASK_SCHEMAS,
)


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
        event.occurred_at,
    )
    with pytest.raises(AuditEventConflict):
        await audit.record(conflicting)

    assert audit.deliveries == 3
    assert audit.entries == (event,)


@pytest.mark.parametrize(
    "outcome",
    (PublishOutcome.CONFIRMED, PublishOutcome.DEDUPLICATED),
)
@pytest.mark.asyncio
async def test_committed_event_is_published_directly(outcome: PublishOutcome) -> None:
    stored = _stored(b'{"task_id":1,"title":"Published"}')
    stream = _RecordingPublisher(outcome)
    events = TaskEventPublisher(TASK_SCHEMAS, cast(StreamPublisher, stream))

    await events.publish_committed(CommitResult((stored,)))

    assert len(stream.calls) == 1
    alias, payload, record_id = stream.calls[0]
    assert alias == "task-events"
    assert record_id == stored.event_id
    assert isinstance(payload, TaskEventRecordV1)
    assert payload.event_id == stored.event_id
    assert payload.kind == "task-created"
    assert payload.task_id == 1
    assert payload.title == "Published"
    assert payload.aggregate_version == 1


@pytest.mark.parametrize(
    "outcome",
    (
        PublishOutcome.REJECTED,
        PublishOutcome.TIMED_OUT,
        PublishOutcome.CLOSED,
        PublishOutcome.BACKPRESSURED,
        PublishOutcome.INDETERMINATE,
    ),
)
@pytest.mark.asyncio
async def test_unconfirmed_direct_publication_is_reported(
    outcome: PublishOutcome,
) -> None:
    stored = _stored(b'{"task_id":1,"title":"Not confirmed"}')
    stream = _RecordingPublisher(outcome)
    events = TaskEventPublisher(TASK_SCHEMAS, cast(StreamPublisher, stream))

    with pytest.raises(TaskEventPublicationError, match=outcome.value):
        await events.publish_committed(CommitResult((stored,)))

    assert len(stream.calls) == 1


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
        datetime.now(UTC),
    )


class _RecordingPublisher:
    def __init__(self, outcome: PublishOutcome) -> None:
        self._outcome = outcome
        self.calls: list[tuple[str, object, UUID | None]] = []

    async def publish(
        self,
        stream: str,
        payload: object,
        *,
        record_id: UUID | None = None,
        headers: Mapping[str, bytes] | None = None,
    ) -> PublishReceipt:
        del headers
        self.calls.append((stream, payload, record_id))
        assert record_id is not None
        return PublishReceipt(record_id, 0, self._outcome)
