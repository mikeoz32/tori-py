"""Stable version 1 JSON schemas for persisted task domain events."""

from __future__ import annotations

import json

from tori_py_cqrs_event_sourcing_core import (
    EventSchema,
    EventSchemaRegistry,
)

from .domain import TaskCreated, TaskRenamed, TaskTitleInvalid, normalize_title

TASK_CREATED_ALIAS = "tasks.task-created"
TASK_RENAMED_ALIAS = "tasks.task-renamed"


def _encode(task_id: int, title: str) -> bytes:
    return json.dumps(
        {"task_id": task_id, "title": title},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _decode(payload: bytes) -> tuple[int, str]:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("task event payload must be an object")
    if set(value) != {"task_id", "title"}:
        raise ValueError("task event payload must contain exactly task_id and title")
    task_id = value["task_id"]
    title = value["title"]
    if isinstance(task_id, bool) or not isinstance(task_id, int):
        raise ValueError("task event ID must be an integer")
    if not isinstance(title, str):
        raise ValueError("task event title must be a string")
    try:
        normalized = normalize_title(title)
    except TaskTitleInvalid as error:
        raise ValueError("task event title violates the title invariant") from error
    if normalized != title:
        raise ValueError("task event title must already be normalized")
    return task_id, title


def build_task_schemas() -> EventSchemaRegistry:
    registry = EventSchemaRegistry()
    registry.register(
        EventSchema(
            TASK_CREATED_ALIAS,
            1,
            TaskCreated,
            lambda event: _encode(event.task_id, event.title),
            lambda payload: TaskCreated(*_decode(payload)),
        )
    )
    registry.register(
        EventSchema(
            TASK_RENAMED_ALIAS,
            1,
            TaskRenamed,
            lambda event: _encode(event.task_id, event.title),
            lambda payload: TaskRenamed(*_decode(payload)),
        )
    )
    return registry.freeze()


TASK_SCHEMAS = build_task_schemas()

__all__ = [
    "TASK_CREATED_ALIAS",
    "TASK_RENAMED_ALIAS",
    "TASK_SCHEMAS",
    "build_task_schemas",
]
