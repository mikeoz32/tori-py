"""SQLAlchemy persistence for the Task API."""

from sqlalchemy import select
from tori_py_sqlalchemy import Repository, SqlAlchemyModule, repository

from .database import TaskRow


@repository(TaskRow)
class TaskRepository(Repository[TaskRow]):
    async def all_ordered(self) -> tuple[TaskRow, ...]:
        rows = await self._scalars(select(TaskRow).order_by(TaskRow.id))
        return tuple(rows)


task_persistence = SqlAlchemyModule.for_feature([TaskRepository])
