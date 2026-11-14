"""Event-sourced task persistence and process-local task IDs."""

from tori_py_cqrs_event_sourcing import aggregate_repository
from tori_py_cqrs_event_sourcing_core import EventSourcedRepository

from .domain import TaskAggregate

EVENT_STORE_KEY = "tasks"


@aggregate_repository(TaskAggregate, category="task", id_encoder=str)
class TaskRepository(EventSourcedRepository[int, TaskAggregate]):
    pass


class TaskIdSequence:
    def __init__(self) -> None:
        self._next_id = 1

    def next(self) -> int:
        task_id = self._next_id
        self._next_id += 1
        return task_id
