"""The task aggregate and the domain events it records."""

from dataclasses import dataclass

from tori_py_cqrs_core import Event
from tori_py_cqrs_event_sourcing_core import AggregateRoot

from .models import TaskTitleInvalid


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
    if not 1 <= len(title) <= 120:
        raise TaskTitleInvalid
    return title


class TaskAggregate(AggregateRoot[int]):
    """A task whose state is rebuilt only from its own events."""

    def __init__(self, task_id: int) -> None:
        super().__init__(task_id)
        self.title = ""

    def create(self, title: str) -> None:
        if self.version or self.pending_events:
            raise RuntimeError("the task is already created")
        self.raise_event(TaskCreated(self.id, normalize_title(title)))

    def rename(self, title: str) -> None:
        normalized = normalize_title(title)
        if normalized != self.title:
            self.raise_event(TaskRenamed(self.id, normalized))

    def _apply(self, event: Event) -> None:
        match event:
            case TaskCreated(title=title) | TaskRenamed(title=title):
                self.title = title
            case _:
                raise TypeError(f"unknown task event: {event!r}")
