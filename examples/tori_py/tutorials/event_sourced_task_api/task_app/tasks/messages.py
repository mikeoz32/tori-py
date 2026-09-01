"""Local CQRS commands for the task command service."""

from dataclasses import dataclass

from tori_py_cqrs_core import Command

from ..contracts import Task


@dataclass(frozen=True, slots=True)
class CreateTask(Command[Task]):
    title: str


@dataclass(frozen=True, slots=True)
class RenameTask(Command[Task]):
    task_id: int
    title: str


__all__ = ["CreateTask", "RenameTask"]
