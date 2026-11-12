"""Task application service."""

from tori_py_sqlalchemy import EntityManager

from .database import TaskRow
from .models import (
    CreateTaskBody,
    CreateTasksBody,
    Task,
    TaskNotFound,
    TaskTitleInvalid,
)
from .state import TaskRepository


class TaskService:
    def __init__(self, repository: TaskRepository, entities: EntityManager) -> None:
        self._repository = repository
        self._entities = entities

    async def create(self, body: CreateTaskBody) -> Task:
        row = await self._repository.add(TaskRow(title=_normalize(body.title)))
        return _to_task(row)

    async def create_many(self, body: CreateTasksBody) -> list[Task]:
        async with self._entities.transaction():
            rows = [
                await self._repository.add(TaskRow(title=_normalize(title)))
                for title in body.titles
            ]
        return [_to_task(row) for row in rows]

    async def get(self, task_id: int) -> Task:
        row = await self._repository.get(task_id)
        if row is None:
            raise TaskNotFound
        return _to_task(row)

    async def all(self) -> list[Task]:
        return [_to_task(row) for row in await self._repository.all_ordered()]


def _normalize(title: str) -> str:
    title = title.strip()
    if not 1 <= len(title) <= 120:
        raise TaskTitleInvalid
    return title


def _to_task(row: TaskRow) -> Task:
    return Task(row.id, row.title)
