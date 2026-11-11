"""Commands, queries, and events for the Task API."""

from dataclasses import dataclass

from tori_py_cqrs_core import Command, Event, Query

from .models import CreateTaskBody, Task


@dataclass(frozen=True, slots=True)
class CreateTask(Command[Task]):
    body: CreateTaskBody


@dataclass(frozen=True, slots=True)
class GetTask(Query[Task]):
    task_id: int


@dataclass(frozen=True, slots=True)
class ListTasks(Query[list[Task]]):
    pass


@dataclass(frozen=True, slots=True)
class TaskCreated(Event):
    task: Task
