"""Task-owned in-memory repository and local metrics sink."""

from __future__ import annotations

import asyncio

from ..contracts import Task
from .models import TaskNotFound


class TaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[int, Task] = {}
        self._next_id = 1

    def create(self, title: str) -> Task:
        task = Task(self._next_id, title)
        self._tasks[task.id] = task
        self._next_id += 1
        return task

    def get(self, task_id: int) -> Task:
        try:
            return self._tasks[task_id]
        except KeyError as error:
            raise TaskNotFound from error

    def all(self) -> list[Task]:
        return [self._tasks[task_id] for task_id in sorted(self._tasks)]


class TaskMetrics:
    """Condition-backed local reaction to the CQRS event."""

    def __init__(self) -> None:
        self.created = 0
        self._changed = asyncio.Condition()

    async def record_created(self) -> None:
        async with self._changed:
            self.created += 1
            self._changed.notify_all()

    async def wait_for_created(self, count: int, *, timeout: float) -> None:
        async with self._changed:
            await asyncio.wait_for(
                self._changed.wait_for(lambda: self.created >= count),
                timeout,
            )


__all__ = ["TaskMetrics", "TaskRepository"]
