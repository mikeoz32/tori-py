"""Task application service."""

from .feed import TaskFeed
from .models import CreateTaskBody, Task, TaskTitleInvalid
from .state import TaskRepository


class TaskService:
    def __init__(self, repository: TaskRepository, feed: TaskFeed) -> None:
        self._repository = repository
        self._feed = feed

    def create(self, body: CreateTaskBody) -> Task:
        title = body.title.strip()
        if not 1 <= len(title) <= 120:
            raise TaskTitleInvalid
        task = self._repository.create(title)
        self._feed.notify()
        return task

    def get(self, task_id: int) -> Task:
        return self._repository.get(task_id)

    def all(self) -> list[Task]:
        return self._repository.all()

    def created_after(self, task_id: int) -> list[Task]:
        return [task for task in self._repository.all() if task.id > task_id]
