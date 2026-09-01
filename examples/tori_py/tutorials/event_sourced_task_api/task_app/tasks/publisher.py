"""Direct publication of committed task events to Persistent Streams."""

from __future__ import annotations

from typing import Annotated

from tori_py import Inject
from tori_py_cqrs_event_sourcing import get_schema_registry_token
from tori_py_cqrs_event_sourcing_core import (
    CommitResult,
    EventSchemaRegistry,
    StoredEvent,
)
from tori_py_persistent_streams import StreamPublisher
from tori_py_persistent_streams_core import PublishOutcome

from ..streams import TASK_EVENTS_ALIAS, TaskEventRecordV1
from .domain import TaskCreated, TaskRenamed

EVENT_SOURCING_KEY = "tasks"


class TaskEventPublicationError(RuntimeError):
    """A committed task event was not confirmed by the stream."""


class TaskEventPublisher:
    """Publish the events from a confirmed command commit directly."""

    def __init__(
        self,
        schemas: Annotated[
            EventSchemaRegistry,
            Inject(get_schema_registry_token(key=EVENT_SOURCING_KEY)),
        ],
        publisher: StreamPublisher,
    ) -> None:
        self._schemas = schemas
        self._publisher = publisher

    async def publish_committed(self, result: CommitResult) -> None:
        for stored in result.events:
            record = self._record(stored)
            receipt = await self._publisher.publish(
                TASK_EVENTS_ALIAS,
                record,
                record_id=record.event_id,
            )
            if receipt.outcome not in {
                PublishOutcome.CONFIRMED,
                PublishOutcome.DEDUPLICATED,
            }:
                raise TaskEventPublicationError(
                    f"task event publication stopped with {receipt.outcome.value}"
                )

    def _record(self, stored: StoredEvent) -> TaskEventRecordV1:
        if stored.stream_id.category != "task":
            raise TaskEventPublicationError("unsupported event-store category")
        recorded = self._schemas.decode(stored)
        match recorded.event:
            case TaskCreated(task_id=task_id, title=title):
                kind = "task-created"
            case TaskRenamed(task_id=task_id, title=title):
                kind = "task-renamed"
            case _:
                raise TaskEventPublicationError("unsupported task domain event")
        return TaskEventRecordV1(
            event_id=stored.event_id,
            kind=kind,
            task_id=task_id,
            title=title,
            aggregate_version=stored.stream_version,
            occurred_at=stored.event.metadata.occurred_at,
        )


__all__ = [
    "EVENT_SOURCING_KEY",
    "TaskEventPublicationError",
    "TaskEventPublisher",
]
