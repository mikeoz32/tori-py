"""Command, query, and event handlers discovered from the module graph."""

from tori_py import Scope
from tori_py_cqrs import command_handler, event_handler, query_handler
from tori_py_cqrs_core import EventBus

from .models import (
    AuditEntry,
    CreateTask,
    GetTask,
    ListTasks,
    Task,
    TaskCreated,
    TaskTitleInvalid,
)
from .state import TaskAuditLog, TaskProjection, TaskRepository


@command_handler(CreateTask, scope=Scope.REQUEST)
class CreateTaskHandler:
    def __init__(self, repository: TaskRepository, events: EventBus) -> None:
        self._repository = repository
        self._events = events

    async def handle(self, command: CreateTask) -> Task:
        title = command.title.strip()
        if not title or len(title) > 120:
            raise TaskTitleInvalid

        task = self._repository.create(title, command.actor)
        await self._events.publish(TaskCreated(task))
        return task


@event_handler(TaskCreated, scope=Scope.REQUEST)
class ProjectTaskCreated:
    def __init__(self, projection: TaskProjection) -> None:
        self._projection = projection

    async def handle(self, event: TaskCreated) -> None:
        await self._projection.apply(event)


@event_handler(TaskCreated, scope=Scope.TRANSIENT)
class AuditTaskCreated:
    def __init__(self, audit: TaskAuditLog) -> None:
        self._audit = audit

    async def handle(self, event: TaskCreated) -> None:
        await self._audit.record(AuditEntry(event.task.id, event.task.created_by))


@query_handler(GetTask, scope=Scope.TRANSIENT)
class GetTaskHandler:
    def __init__(self, projection: TaskProjection) -> None:
        self._projection = projection

    async def handle(self, query: GetTask) -> Task:
        return self._projection.get(query.task_id)


@query_handler(ListTasks, scope=Scope.TRANSIENT)
class ListTasksHandler:
    def __init__(self, projection: TaskProjection) -> None:
        self._projection = projection

    async def handle(self, query: ListTasks) -> list[Task]:
        return self._projection.all()
