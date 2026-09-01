"""Request-scoped task aggregate repository declaration."""

from tori_py_cqrs_event_sourcing import aggregate_repository
from tori_py_cqrs_event_sourcing_core import EventSourcedRepository

from .domain import TaskAggregate


@aggregate_repository(TaskAggregate, category="task", id_encoder=str)
class TaskRepository(EventSourcedRepository[int, TaskAggregate]):
    pass


__all__ = ["TaskRepository"]
