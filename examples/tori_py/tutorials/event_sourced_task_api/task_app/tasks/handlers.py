"""Request-scoped event-sourced task command handlers."""

from __future__ import annotations

from typing import Annotated

from tori_py import Inject, Scope
from tori_py_cqrs import command_handler
from tori_py_cqrs_event_sourcing import (
    CommandSynchronization,
    aggregate_repository,
    get_command_synchronization_token,
    use_event_sourcing,
)

from ..contracts import Task
from .domain import TaskAggregate, normalize_title
from .messages import CreateTask, RenameTask
from .relay import EVENT_SOURCING_KEY, TaskEventRelay
from .repository import TaskRepository
from .state import TaskIdSequence


class _HandlerBase:
    def __init__(
        self,
        synchronization: Annotated[
            CommandSynchronization,
            Inject(get_command_synchronization_token(key=EVENT_SOURCING_KEY)),
        ],
        relay: TaskEventRelay,
    ) -> None:
        self._synchronization = synchronization
        self._relay = relay

    def _wake_relay_after_commit(self) -> None:
        self._synchronization.after_commit(self._relay.after_commit)


@use_event_sourcing(key=EVENT_SOURCING_KEY)
@command_handler(CreateTask, scope=Scope.REQUEST)
class CreateTaskHandler(_HandlerBase):
    def __init__(
        self,
        repository: Annotated[
            TaskRepository,
            aggregate_repository(TaskRepository),
        ],
        ids: TaskIdSequence,
        synchronization: Annotated[
            CommandSynchronization,
            Inject(get_command_synchronization_token(key=EVENT_SOURCING_KEY)),
        ],
        relay: TaskEventRelay,
    ) -> None:
        super().__init__(synchronization, relay)
        self._repository = repository
        self._ids = ids

    async def handle(self, command: CreateTask) -> Task:
        self._relay.require_available()
        title = normalize_title(command.title)
        aggregate = TaskAggregate(self._ids.next())
        aggregate.create(title)
        self._repository.save(aggregate)
        self._wake_relay_after_commit()
        return Task(aggregate.id, aggregate.title)


@use_event_sourcing(key=EVENT_SOURCING_KEY)
@command_handler(RenameTask, scope=Scope.REQUEST)
class RenameTaskHandler(_HandlerBase):
    def __init__(
        self,
        repository: Annotated[
            TaskRepository,
            aggregate_repository(TaskRepository),
        ],
        synchronization: Annotated[
            CommandSynchronization,
            Inject(get_command_synchronization_token(key=EVENT_SOURCING_KEY)),
        ],
        relay: TaskEventRelay,
    ) -> None:
        super().__init__(synchronization, relay)
        self._repository = repository

    async def handle(self, command: RenameTask) -> Task:
        self._relay.require_available()
        title = normalize_title(command.title)
        aggregate = await self._repository.get(command.task_id)
        aggregate.rename(title)
        if aggregate.pending_events:
            self._repository.save(aggregate)
            self._wake_relay_after_commit()
        return Task(aggregate.id, aggregate.title)


__all__ = ["CreateTaskHandler", "RenameTaskHandler"]
