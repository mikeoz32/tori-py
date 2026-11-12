"""The versioned task activity record and its persistent stream contract."""

from typing import Protocol
from uuid import UUID

import msgspec
from tori_py_persistent_streams import StreamBinding, stream_publish
from tori_py_persistent_streams_core import (
    Beginning,
    ExternalCheckpointStrategy,
    InMemoryCheckpointStore,
    PublishReceipt,
    StreamDefinition,
)

TASK_ACTIVITY = "task-activity"
TASK_ACTIVITY_STREAM = StreamDefinition("tutorial-task-activity-v1", partition_count=2)


class TaskCreatedV1(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Version 1 of the record published after a task is created."""

    task_id: int
    title: str


class TaskCreatedCodec:
    def encode(self, payload: TaskCreatedV1) -> bytes:
        return msgspec.json.encode(payload)

    def decode(self, payload: bytes, target: type[TaskCreatedV1]) -> TaskCreatedV1:
        return msgspec.json.decode(payload, type=target)


class TaskIdPartitionKey:
    def resolve(self, payload: TaskCreatedV1) -> bytes:
        return str(payload.task_id).encode("ascii")


def task_activity_binding(
    checkpoints: InMemoryCheckpointStore,
) -> StreamBinding[TaskCreatedV1]:
    return StreamBinding(
        alias=TASK_ACTIVITY,
        definition=TASK_ACTIVITY_STREAM,
        payload_type=TaskCreatedV1,
        codec=TaskCreatedCodec(),
        partition_key_resolver=TaskIdPartitionKey(),
        start=Beginning(),
        checkpoint_strategy=ExternalCheckpointStrategy(
            "task-activity-log-v1",
            checkpoints,
        ),
    )


class TaskActivityPublisher(Protocol):
    @stream_publish(payload=TaskCreatedV1)
    async def task_created(
        self,
        payload: TaskCreatedV1,
        *,
        record_id: UUID | None = None,
    ) -> PublishReceipt: ...
