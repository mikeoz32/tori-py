"""Local task command, query, and event handlers."""

from tori_py_cqrs import command_handler, event_handler, query_handler
from tori_py_cqrs_core import EventBus

from ..contracts import Task
from .models import CreateTask, GetTask, ListTasks, TaskCreated, TaskTitleInvalid
from .state import TaskMetrics, TaskRepository


@command_handler(CreateTask)
class CreateTaskHandler:
    def __init__(self, repository: TaskRepository, events: EventBus) -> None:
        self._repository = repository
        self._events = events

    async def handle(self, command: CreateTask) -> Task:
        title = command.title.strip()
        if not title or len(title) > 120:
            raise TaskTitleInvalid
        task = self._repository.create(title)
        await self._events.publish(TaskCreated(task))
        return task


@query_handler(ListTasks)
class ListTasksHandler:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def handle(self, query: ListTasks) -> list[Task]:
        del query
        return self._repository.all()


@query_handler(GetTask)
class GetTaskHandler:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def handle(self, query: GetTask) -> Task:
        return self._repository.get(query.task_id)


@event_handler(TaskCreated)
class CountTaskCreated:
    def __init__(self, metrics: TaskMetrics) -> None:
        self._metrics = metrics

    async def handle(self, event: TaskCreated) -> None:
        del event
        await self._metrics.record_created()


__all__ = [
    "CountTaskCreated",
    "CreateTaskHandler",
    "GetTaskHandler",
    "ListTasksHandler",
]
