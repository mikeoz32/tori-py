"""Task application service."""

from .models import CreateTaskBody, Task, TaskTitleInvalid
from .state import TaskRepository


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    def create(self, body: CreateTaskBody) -> Task:
        title = body.title.strip()
        if not 1 <= len(title) <= 120:
            raise TaskTitleInvalid
        return self._repository.create(title)

    def get(self, task_id: int) -> Task:
        return self._repository.get(task_id)

    def all(self) -> list[Task]:
        return self._repository.all()
