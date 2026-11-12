"""Aggregate, schema, and Unit of Work tests without the ToriPy application."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from tori_py_cqrs_event_sourcing_core import (
    AppendEvent,
    EncodedEvent,
    EventMetadata,
    EventSourcingUnitOfWork,
    InMemoryEventStore,
    OptimisticConcurrencyError,
    StreamId,
)

from .domain import TaskAggregate, TaskCreated, TaskRenamed
from .models import Task, TaskTitleInvalid
from .projection import TaskProjection, VersionedTask
from .schemas import TASK_CREATED, TASK_SCHEMAS
from .state import TaskRepository


def repository(unit_of_work: EventSourcingUnitOfWork) -> TaskRepository:
    return TaskRepository(
        unit_of_work,
        category="task",
        aggregate_factory=TaskAggregate,
        aggregate_type=TaskAggregate,
        id_encoder=str,
        schemas=TASK_SCHEMAS,
    )


def test_aggregate_records_events_and_keeps_the_title_rule() -> None:
    task = TaskAggregate(1)
    task.create("  Plan  ")
    task.rename("Plan")
    task.rename("Ship")

    assert task.title == "Ship"
    assert task.version == 0
    assert [pending.event for pending in task.pending_events] == [
        TaskCreated(1, "Plan"),
        TaskRenamed(1, "Ship"),
    ]
    with pytest.raises(TaskTitleInvalid):
        task.rename("   ")


@pytest.mark.asyncio
async def test_unit_of_work_commits_and_replays_a_task() -> None:
    store = InMemoryEventStore()

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        task = TaskAggregate(1)
        task.create("Plan")
        task.rename("Ship")
        repository(unit_of_work).save(task)
        await unit_of_work.commit()
    assert task.version == 2
    assert task.pending_events == ()

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        replayed = await repository(unit_of_work).get(1)
    assert (replayed.title, replayed.version) == ("Ship", 2)


@pytest.mark.asyncio
async def test_version_one_events_are_upcast_on_read() -> None:
    store = InMemoryEventStore()
    async with store.transaction() as transaction:
        transaction.append(
            StreamId("task", "7"),
            expected_version=0,
            events=[
                AppendEvent(
                    EncodedEvent(TASK_CREATED, 1, b'{"id":7,"name":"Legacy"}'),
                    EventMetadata(event_id=uuid4(), occurred_at=datetime.now(UTC)),
                )
            ],
        )
        await transaction.commit()

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        task = await repository(unit_of_work).get(7)
    assert task.title == "Legacy"

    projection = TaskProjection(store, TASK_SCHEMAS)
    await projection.catch_up()
    assert projection.get(7) == VersionedTask(Task(7, "Legacy"), 1)
    assert projection.checkpoint == 1


@pytest.mark.asyncio
async def test_the_second_writer_of_a_version_gets_a_conflict() -> None:
    store = InMemoryEventStore()
    async with EventSourcingUnitOfWork(store) as unit_of_work:
        task = TaskAggregate(1)
        task.create("Plan")
        repository(unit_of_work).save(task)
        await unit_of_work.commit()

    first = EventSourcingUnitOfWork(store)
    second = EventSourcingUnitOfWork(store)
    async with first, second:
        my_tasks, their_tasks = repository(first), repository(second)
        mine = await my_tasks.get(1)
        theirs = await their_tasks.get(1)
        mine.rename("Mine")
        theirs.rename("Theirs")
        my_tasks.save(mine)
        their_tasks.save(theirs)
        await first.commit()
        with pytest.raises(OptimisticConcurrencyError) as conflict:
            await second.commit()

    assert (conflict.value.expected_version, conflict.value.actual_version) == (1, 2)
    assert theirs.is_faulted
