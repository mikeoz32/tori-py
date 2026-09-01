"""Idempotent, version-checked in-memory task projection."""

from __future__ import annotations

import asyncio
from uuid import UUID

from ..contracts import Task
from ..streams import TaskEventRecordV1


class TaskProjectionMiss(Exception):
    """Raised when a task is absent from the current projection."""


class ProjectionUnavailable(Exception):
    """Raised after a projection invariant has been violated."""


class ProjectionCorruption(ProjectionUnavailable):
    """A record conflicted with event identity or aggregate version history."""


class TaskProjectionState:
    """Apply task records exactly once by identity and in aggregate order."""

    def __init__(self) -> None:
        self._tasks: dict[int, Task] = {}
        self._versions: dict[int, int] = {}
        self._events: dict[UUID, TaskEventRecordV1] = {}
        self._unavailable = False
        self.deliveries = 0
        self._changed = asyncio.Condition()

    @property
    def unavailable(self) -> bool:
        return self._unavailable

    @property
    def event_count(self) -> int:
        return len(self._events)

    def all(self) -> list[Task]:
        self._require_available()
        return [self._tasks[task_id] for task_id in sorted(self._tasks)]

    def get(self, task_id: int) -> Task:
        self._require_available()
        try:
            return self._tasks[task_id]
        except KeyError as error:
            raise TaskProjectionMiss from error

    def version(self, task_id: int) -> int | None:
        return self._versions.get(task_id)

    async def apply(self, record: TaskEventRecordV1) -> None:
        async with self._changed:
            self.deliveries += 1
            existing = self._events.get(record.event_id)
            if existing is not None:
                if existing != record:
                    self._fail("event ID was reused with different contents")
                self._changed.notify_all()
                return
            if self._unavailable:
                raise ProjectionUnavailable("task projection is unavailable")

            current_version = self._versions.get(record.task_id)
            if record.kind == "task-created":
                if record.aggregate_version != 1 or current_version is not None:
                    self._fail("task-created must be aggregate version 1")
            elif current_version is None or record.aggregate_version != (
                current_version + 1
            ):
                self._fail("task-renamed contains an aggregate version gap")

            self._tasks[record.task_id] = Task(record.task_id, record.title)
            self._versions[record.task_id] = record.aggregate_version
            self._events[record.event_id] = record
            self._changed.notify_all()

    async def wait_for_version(
        self,
        task_id: int,
        version: int,
        *,
        timeout: float,
    ) -> None:
        async with self._changed:
            await asyncio.wait_for(
                self._changed.wait_for(
                    lambda: (
                        self._versions.get(task_id, 0) >= version or self._unavailable
                    )
                ),
                timeout,
            )
        self._require_available()

    async def wait_for_deliveries(self, count: int, *, timeout: float) -> None:
        async with self._changed:
            await asyncio.wait_for(
                self._changed.wait_for(
                    lambda: self.deliveries >= count or self._unavailable
                ),
                timeout,
            )
        self._require_available()

    def _require_available(self) -> None:
        if self._unavailable:
            raise ProjectionUnavailable("task projection is unavailable")

    def _fail(self, message: str) -> None:
        self._unavailable = True
        self._changed.notify_all()
        raise ProjectionCorruption(message)


__all__ = [
    "ProjectionCorruption",
    "ProjectionUnavailable",
    "TaskProjectionMiss",
    "TaskProjectionState",
]
