"""Task application service coordinating local CQRS and integration events."""

from uuid import uuid4

from tori_py_cqrs_core import CommandBus, QueryBus
from tori_py_microservices import EventDispatcher

from ..contracts import Task, TaskCreatedV1
from .models import CreateTask, GetTask, ListTasks


class TaskApplicationService:
    def __init__(
        self,
        commands: CommandBus,
        queries: QueryBus,
        integration_events: EventDispatcher,
    ) -> None:
        self._commands = commands
        self._queries = queries
        self._integration_events = integration_events

    async def create(self, title: str) -> Task:
        task = await self._commands.execute(CreateTask(title))
        await self._integration_events.publish(
            "task-created",
            1,
            TaskCreatedV1(uuid4(), task.id, task.title),
            require_route=True,
        )
        return task

    async def list_tasks(self) -> list[Task]:
        return await self._queries.execute(ListTasks())

    async def get(self, task_id: int) -> Task:
        return await self._queries.execute(GetTask(task_id))


__all__ = ["TaskApplicationService"]
