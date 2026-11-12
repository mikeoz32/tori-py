"""Task application service."""

from tori_py_persistent_streams_core import PublishOutcome

from .activity import TaskActivityPublisher, TaskCreatedV1
from .models import CreateTaskBody, Task, TaskTitleInvalid
from .state import TaskRepository


class ActivityNotRecorded(Exception):
    """Raised when the stream did not confirm a task's activity record."""


class TaskService:
    def __init__(
        self,
        repository: TaskRepository,
        activity: TaskActivityPublisher,
    ) -> None:
        self._repository = repository
        self._activity = activity

    async def create(self, body: CreateTaskBody) -> Task:
        title = body.title.strip()
        if not 1 <= len(title) <= 120:
            raise TaskTitleInvalid
        task = self._repository.create(title)
        receipt = await self._activity.task_created(TaskCreatedV1(task.id, task.title))
        if receipt.outcome is not PublishOutcome.CONFIRMED:
            raise ActivityNotRecorded
        return task

    def get(self, task_id: int) -> Task:
        return self._repository.get(task_id)

    def all(self) -> list[Task]:
        return self._repository.all()
