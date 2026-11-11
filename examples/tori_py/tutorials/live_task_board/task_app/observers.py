"""In-memory observers for task-created events."""

import asyncio

from .models import Task


class TaskAuditLog:
    def __init__(self) -> None:
        self.entries: list[Task] = []
        self._changed = asyncio.Condition()

    async def record(self, task: Task) -> None:
        async with self._changed:
            self.entries.append(task)
            self._changed.notify_all()

    async def wait_for_count(self, count: int, *, timeout: float) -> None:
        async with self._changed:
            await asyncio.wait_for(
                self._changed.wait_for(lambda: len(self.entries) >= count),
                timeout,
            )


class TaskMetrics:
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
