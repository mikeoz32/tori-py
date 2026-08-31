"""HTTP models, application messages, and errors."""

from dataclasses import dataclass

import msgspec
from tori_py_cqrs_core import Command, Event, Query


class Task(msgspec.Struct, frozen=True):
    id: int
    title: str
    created_by: str


class CreateTaskBody(msgspec.Struct):
    title: str


class AuditEntry(msgspec.Struct, frozen=True):
    task_id: int
    actor: str


class TaskTitleInvalid(Exception):
    pass


class TaskNotFound(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CreateTask(Command[Task]):
    title: str
    actor: str


@dataclass(frozen=True, slots=True)
class GetTask(Query[Task]):
    task_id: int


@dataclass(frozen=True, slots=True)
class ListTasks(Query[list[Task]]):
    pass


@dataclass(frozen=True, slots=True)
class TaskCreated(Event):
    task: Task
