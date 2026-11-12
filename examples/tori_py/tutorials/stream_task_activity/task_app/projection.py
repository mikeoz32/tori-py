"""A read model that a stream handler builds from task activity records."""

from typing import Annotated
from uuid import UUID

import msgspec
from tori_py import controller
from tori_py_persistent_streams import (
    StreamContext,
    StreamPayload,
    StreamRecordContext,
    stream_handler,
)

from .activity import TASK_ACTIVITY, TaskCreatedV1


class ActivityEntry(msgspec.Struct, frozen=True):
    task_id: int
    title: str
    partition: int
    offset: int


class ActivityLog:
    """Entries keyed by record ID, so a redelivered record changes nothing."""

    def __init__(self) -> None:
        self._entries: dict[UUID, ActivityEntry] = {}

    def record(self, record_id: UUID, entry: ActivityEntry) -> None:
        self._entries.setdefault(record_id, entry)

    def entries(self) -> list[ActivityEntry]:
        return sorted(self._entries.values(), key=lambda entry: entry.task_id)


@controller()
class ActivityProjection:
    def __init__(self, log: ActivityLog) -> None:
        self._log = log

    @stream_handler(stream=TASK_ACTIVITY, consumer_group="task-activity-log-v1")
    async def apply(
        self,
        payload: Annotated[TaskCreatedV1, StreamPayload()],
        record: Annotated[StreamContext, StreamRecordContext()],
    ) -> None:
        self._log.record(
            record.record_id,
            ActivityEntry(
                task_id=payload.task_id,
                title=payload.title,
                partition=record.partition,
                offset=record.offset,
            ),
        )
