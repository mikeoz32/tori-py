"""A read model rebuilt from the event store's global order."""

import asyncio
from dataclasses import dataclass
from typing import Annotated

from tori_py import Inject
from tori_py_cqrs_event_sourcing import get_event_store_token, get_schema_registry_token
from tori_py_cqrs_event_sourcing_core import (
    EventSchemaRegistry,
    EventStore,
    RecordedEvent,
)

from .domain import TaskCreated, TaskRenamed
from .models import Task, TaskNotFound
from .state import EVENT_STORE_KEY


@dataclass(frozen=True, slots=True)
class VersionedTask:
    task: Task
    version: int


class TaskProjection:
    def __init__(
        self,
        store: Annotated[
            EventStore, Inject(get_event_store_token(key=EVENT_STORE_KEY))
        ],
        schemas: Annotated[
            EventSchemaRegistry,
            Inject(get_schema_registry_token(key=EVENT_STORE_KEY)),
        ],
    ) -> None:
        self._store = store
        self._schemas = schemas
        self._tasks: dict[int, VersionedTask] = {}
        self._checkpoint = 0
        self._lock = asyncio.Lock()

    @property
    def checkpoint(self) -> int:
        """Return the global position of the last applied event."""

        return self._checkpoint

    async def catch_up(self) -> None:
        """Apply every event committed after the checkpoint."""

        page_size = self._schemas.limits.read_page_size
        async with self._lock:
            while True:
                page = await self._store.read_all(
                    after_position=self._checkpoint,
                    limit=page_size,
                )
                for stored in page:
                    self._apply(self._schemas.decode(stored))
                    self._checkpoint = stored.global_position
                if len(page) < page_size:
                    return

    def get(self, task_id: int) -> VersionedTask:
        try:
            return self._tasks[task_id]
        except KeyError as error:
            raise TaskNotFound from error

    def all(self) -> list[Task]:
        return [self._tasks[task_id].task for task_id in sorted(self._tasks)]

    def _apply(self, recorded: RecordedEvent) -> None:
        match recorded.event:
            case (
                TaskCreated(task_id=task_id, title=title)
                | TaskRenamed(task_id=task_id, title=title)
            ):
                self._tasks[task_id] = VersionedTask(
                    Task(task_id, title),
                    recorded.stream_version,
                )
