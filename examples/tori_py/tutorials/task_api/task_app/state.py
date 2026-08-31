"""In-memory persistence for the Task API."""

from .models import Task, TaskNotFound


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
