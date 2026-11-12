"""Commands and queries for the event-sourced Task API."""

from dataclasses import dataclass

from tori_py_cqrs_core import Command, Query

from .models import CreateTaskBody, RenameTaskBody, Task
from .projection import VersionedTask


@dataclass(frozen=True, slots=True)
class CreateTask(Command[VersionedTask]):
    body: CreateTaskBody


@dataclass(frozen=True, slots=True)
class RenameTask(Command[VersionedTask]):
    task_id: int
    body: RenameTaskBody
    expected_version: int | None = None


@dataclass(frozen=True, slots=True)
class GetTask(Query[VersionedTask]):
    task_id: int


@dataclass(frozen=True, slots=True)
class ListTasks(Query[list[Task]]):
    pass
