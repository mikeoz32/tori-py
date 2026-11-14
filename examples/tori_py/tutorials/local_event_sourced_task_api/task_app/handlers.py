"""Command handlers that write events and query handlers that read the projection."""

from typing import Annotated

from tori_py import Inject, Scope
from tori_py_cqrs import command_handler, query_handler
from tori_py_cqrs_event_sourcing import (
    CommandSynchronization,
    aggregate_repository,
    get_command_synchronization_token,
    use_event_sourcing,
)

from .domain import TaskAggregate, normalize_title
from .messages import CreateTask, GetTask, ListTasks, RenameTask
from .models import Task, TaskNotFound, TaskVersionMismatch
from .projection import TaskProjection, VersionedTask
from .reconciliation import ReconciliationLog
from .state import EVENT_STORE_KEY, TaskIdSequence, TaskRepository


@use_event_sourcing(key=EVENT_STORE_KEY)
@command_handler(CreateTask, scope=Scope.REQUEST)
class CreateTaskHandler:
    def __init__(
        self,
        tasks: Annotated[TaskRepository, aggregate_repository(TaskRepository)],
        ids: TaskIdSequence,
        synchronization: Annotated[
            CommandSynchronization,
            Inject(get_command_synchronization_token(key=EVENT_STORE_KEY)),
        ],
        reconciliation: ReconciliationLog,
    ) -> None:
        self._tasks = tasks
        self._ids = ids
        self._synchronization = synchronization
        self._reconciliation = reconciliation

    async def handle(self, command: CreateTask) -> VersionedTask:
        title = normalize_title(command.body.title)
        task = TaskAggregate(self._ids.next())
        task.create(title)
        self._tasks.save(task)
        self._synchronization.after_indeterminate(
            lambda error: self._reconciliation.record(task.id, error)
        )
        return VersionedTask(Task(task.id, task.title), version=1)


@use_event_sourcing(key=EVENT_STORE_KEY)
@command_handler(RenameTask, scope=Scope.REQUEST)
class RenameTaskHandler:
    def __init__(
        self,
        tasks: Annotated[TaskRepository, aggregate_repository(TaskRepository)],
        synchronization: Annotated[
            CommandSynchronization,
            Inject(get_command_synchronization_token(key=EVENT_STORE_KEY)),
        ],
        reconciliation: ReconciliationLog,
    ) -> None:
        self._tasks = tasks
        self._synchronization = synchronization
        self._reconciliation = reconciliation

    async def handle(self, command: RenameTask) -> VersionedTask:
        title = normalize_title(command.body.title)
        task = await self._tasks.load(command.task_id)
        if task is None:
            raise TaskNotFound
        if command.expected_version not in (None, task.version):
            raise TaskVersionMismatch
        task.rename(title)
        if task.pending_events:
            self._tasks.save(task)
            self._synchronization.after_indeterminate(
                lambda error: self._reconciliation.record(task.id, error)
            )
        # The caller receives this only after a confirmed commit, which appends
        # exactly the pending events.
        version = task.version + len(task.pending_events)
        return VersionedTask(Task(task.id, task.title), version)


@query_handler(GetTask)
class GetTaskHandler:
    def __init__(self, projection: TaskProjection) -> None:
        self._projection = projection

    async def handle(self, query: GetTask) -> VersionedTask:
        await self._projection.catch_up()
        return self._projection.get(query.task_id)


@query_handler(ListTasks)
class ListTasksHandler:
    def __init__(self, projection: TaskProjection) -> None:
        self._projection = projection

    async def handle(self, query: ListTasks) -> list[Task]:
        await self._projection.catch_up()
        return self._projection.all()
