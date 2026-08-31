"""Task service application messages and errors."""

from dataclasses import dataclass

from tori_py_cqrs_core import Command, Event, Query

from ..contracts import Task


class TaskTitleInvalid(Exception):
    """Raised when a normalized title violates the task rule."""


class TaskNotFound(Exception):
    """Raised when a task ID is absent from task-owned storage."""


@dataclass(frozen=True, slots=True)
class CreateTask(Command[Task]):
    title: str


@dataclass(frozen=True, slots=True)
class ListTasks(Query[list[Task]]):
    pass


@dataclass(frozen=True, slots=True)
class GetTask(Query[Task]):
    task_id: int


@dataclass(frozen=True, slots=True)
class TaskCreated(Event):
    task: Task


__all__ = [
    "CreateTask",
    "GetTask",
    "ListTasks",
    "TaskCreated",
    "TaskNotFound",
    "TaskTitleInvalid",
]
