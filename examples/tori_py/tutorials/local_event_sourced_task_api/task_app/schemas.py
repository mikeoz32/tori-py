"""Stable stored names, versions, and JSON codecs for task events."""

import msgspec
from tori_py_cqrs_event_sourcing_core import EventSchema, EventSchemaRegistry

from .domain import TaskCreated, TaskRenamed

TASK_CREATED = "tasks.task-created"
TASK_RENAMED = "tasks.task-renamed"


class TaskFields(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """The stored JSON of both task events."""

    task_id: int
    title: str


class TaskCreatedV1(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """The stored JSON of task-created before schema version 2."""

    id: int
    name: str


def encode_task_event(event: TaskCreated | TaskRenamed) -> bytes:
    return msgspec.json.encode(TaskFields(event.task_id, event.title))


def decode_task_created(payload: bytes) -> TaskCreated:
    fields = msgspec.json.decode(payload, type=TaskFields)
    return TaskCreated(fields.task_id, fields.title)


def decode_task_renamed(payload: bytes) -> TaskRenamed:
    fields = msgspec.json.decode(payload, type=TaskFields)
    return TaskRenamed(fields.task_id, fields.title)


def upcast_task_created_v1(payload: bytes) -> bytes:
    """Rewrite stored version 1 JSON into version 2 JSON while reading."""

    old = msgspec.json.decode(payload, type=TaskCreatedV1)
    return msgspec.json.encode(TaskFields(old.id, old.name))


def build_task_schemas() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    registry.register(
        EventSchema(
            TASK_CREATED,
            2,
            TaskCreated,
            encode_task_event,
            decode_task_created,
            upcasters={1: upcast_task_created_v1},
        )
    )
    registry.register(
        EventSchema(
            TASK_RENAMED,
            1,
            TaskRenamed,
            encode_task_event,
            decode_task_renamed,
        )
    )
    return registry.freeze()


TASK_SCHEMAS = build_task_schemas()
