"""Command, query, and event handlers discovered from the module graph."""

from tori_py_cqrs import command_handler, event_handler, query_handler
from tori_py_cqrs_core import EventBus

from .messages import (
    CreateTask,
    GetTask,
    ListTasks,
    TaskCreated,
)
from .models import Task
from .observers import TaskAuditLog, TaskMetrics
from .services import TaskService


@command_handler(CreateTask)
class CreateTaskHandler:
    def __init__(self, tasks: TaskService, events: EventBus) -> None:
        self._tasks = tasks
        self._events = events

    async def handle(self, command: CreateTask) -> Task:
        task = self._tasks.create(command.body)
        await self._events.publish(TaskCreated(task))
        return task


@query_handler(GetTask)
class GetTaskHandler:
    def __init__(self, tasks: TaskService) -> None:
        self._tasks = tasks

    async def handle(self, query: GetTask) -> Task:
        return self._tasks.get(query.task_id)


@query_handler(ListTasks)
class ListTasksHandler:
    def __init__(self, tasks: TaskService) -> None:
        self._tasks = tasks

    async def handle(self, query: ListTasks) -> list[Task]:
        return self._tasks.all()


@event_handler(TaskCreated)
class AuditTaskCreated:
    def __init__(self, audit: TaskAuditLog) -> None:
        self._audit = audit

    async def handle(self, event: TaskCreated) -> None:
        await self._audit.record(event.task)


@event_handler(TaskCreated)
class CountTaskCreated:
    def __init__(self, metrics: TaskMetrics) -> None:
        self._metrics = metrics

    async def handle(self, event: TaskCreated) -> None:
        del event
        await self._metrics.record_created()
