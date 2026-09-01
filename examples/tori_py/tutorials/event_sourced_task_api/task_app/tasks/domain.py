"""Task aggregate, domain events, and title invariant."""

from __future__ import annotations

from dataclasses import dataclass

from tori_py_cqrs_core import Event
from tori_py_cqrs_event_sourcing_core import AggregateRoot


class TaskTitleInvalid(Exception):
    """Raised when a normalized title is outside the accepted length."""


@dataclass(frozen=True, slots=True)
class TaskCreated(Event):
    task_id: int
    title: str


@dataclass(frozen=True, slots=True)
class TaskRenamed(Event):
    task_id: int
    title: str


def normalize_title(value: str) -> str:
    title = value.strip()
    if not title or len(title) > 120:
        raise TaskTitleInvalid
    try:
        title.encode("utf-8")
    except UnicodeEncodeError as error:
        raise TaskTitleInvalid from error
    return title


class TaskAggregate(AggregateRoot[int]):
    """A task rebuilt exclusively from task-created and task-renamed events."""

    def __init__(self, task_id: int) -> None:
        super().__init__(task_id)
        self.title = ""

    def create(self, title: str) -> None:
        if self.version or self.pending_events:
            raise RuntimeError("task aggregate is already created")
        self.raise_event(TaskCreated(self.id, normalize_title(title)))

    def rename(self, title: str) -> None:
        if not self.title:
            raise RuntimeError("task aggregate is not created")
        normalized = normalize_title(title)
        if normalized == self.title:
            return
        self.raise_event(TaskRenamed(self.id, normalized))

    def _apply(self, event: Event) -> None:
        match event:
            case TaskCreated(task_id=task_id, title=title):
                if task_id != self.id or self.title:
                    raise ValueError("task-created does not match the aggregate")
                self.title = title
            case TaskRenamed(task_id=task_id, title=title):
                if task_id != self.id or not self.title:
                    raise ValueError("task-renamed does not match the aggregate")
                self.title = title
            case _:
                raise AssertionError(f"unknown task event: {event!r}")


__all__ = [
    "TaskAggregate",
    "TaskCreated",
    "TaskRenamed",
    "TaskTitleInvalid",
    "normalize_title",
]
