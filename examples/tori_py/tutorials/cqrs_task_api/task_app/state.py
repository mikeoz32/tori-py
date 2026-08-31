"""In-memory write model, read projection, and audit sink."""

import asyncio

from .models import AuditEntry, Task, TaskCreated, TaskNotFound


class TaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[int, Task] = {}
        self._next_id = 1

    def create(self, title: str, actor: str) -> Task:
        task = Task(self._next_id, title, actor)
        self._tasks[task.id] = task
        self._next_id += 1
        return task


class TaskProjection:
    def __init__(self) -> None:
        self._tasks: dict[int, Task] = {}
        self._changed = asyncio.Condition()

    async def apply(self, event: TaskCreated) -> None:
        async with self._changed:
            self._tasks[event.task.id] = event.task
            self._changed.notify_all()

    def get(self, task_id: int) -> Task:
        try:
            return self._tasks[task_id]
        except KeyError as error:
            raise TaskNotFound from error

    def all(self) -> list[Task]:
        return [self._tasks[task_id] for task_id in sorted(self._tasks)]

    async def wait_for_count(self, count: int, *, timeout: float) -> None:
        async with self._changed:
            await asyncio.wait_for(
                self._changed.wait_for(lambda: len(self._tasks) >= count),
                timeout,
            )


class TaskAuditLog:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []
        self._changed = asyncio.Condition()

    async def record(self, entry: AuditEntry) -> None:
        async with self._changed:
            self.entries.append(entry)
            self._changed.notify_all()

    async def wait_for_count(self, count: int, *, timeout: float) -> None:
        async with self._changed:
            await asyncio.wait_for(
                self._changed.wait_for(lambda: len(self.entries) >= count),
                timeout,
            )
