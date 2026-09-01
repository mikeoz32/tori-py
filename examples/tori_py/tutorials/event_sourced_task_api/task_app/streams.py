"""The one versioned persistent-stream contract used by all four roots."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

import msgspec
from tori_py_persistent_streams import StreamBinding
from tori_py_persistent_streams_core import (
    Beginning,
    CheckpointStrategy,
    ExternalCheckpointStrategy,
    InMemoryCheckpointStore,
    StreamDefinition,
)

TASK_EVENTS_ALIAS = "task-events"
TASK_EVENTS_PHYSICAL = "tutorial-task-events-v1"
TASK_EVENTS_DEFINITION = StreamDefinition(TASK_EVENTS_PHYSICAL, partition_count=2)


class TaskEventRecordV1(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Exact version 1 record published from a committed domain event."""

    event_id: UUID
    kind: Literal["task-created", "task-renamed"]
    task_id: int
    title: str
    aggregate_version: int
    occurred_at: datetime


class TaskEventCodec:
    def encode(self, payload: TaskEventRecordV1) -> bytes:
        return msgspec.json.encode(payload)

    def decode(
        self,
        payload: bytes,
        target: type[TaskEventRecordV1],
    ) -> TaskEventRecordV1:
        return msgspec.json.decode(payload, type=target)


class TaskPartitionKey:
    def resolve(self, payload: TaskEventRecordV1) -> bytes:
        return str(payload.task_id).encode("ascii")


def task_event_binding(
    checkpoints: InMemoryCheckpointStore | None = None,
    *,
    checkpoint_identity: str = "task-events-v1",
) -> StreamBinding[TaskEventRecordV1]:
    """Build the fixed binding with optional process-local checkpoints."""

    strategy = (
        CheckpointStrategy.BROKER_MANAGED
        if checkpoints is None
        else ExternalCheckpointStrategy(checkpoint_identity, checkpoints)
    )
    return StreamBinding(
        alias=TASK_EVENTS_ALIAS,
        definition=TASK_EVENTS_DEFINITION,
        payload_type=TaskEventRecordV1,
        codec=TaskEventCodec(),
        partition_key_resolver=TaskPartitionKey(),
        start=Beginning(),
        checkpoint_strategy=strategy,
    )


__all__ = [
    "TASK_EVENTS_ALIAS",
    "TASK_EVENTS_DEFINITION",
    "TASK_EVENTS_PHYSICAL",
    "TaskEventCodec",
    "TaskEventRecordV1",
    "TaskPartitionKey",
    "task_event_binding",
]
