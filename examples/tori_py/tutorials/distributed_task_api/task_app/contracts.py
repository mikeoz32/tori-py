"""Shared versioned wire contracts for the task system."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

import msgspec
from tori_py_microservices import ServiceIdentity, rpc_call, service_contract

TASKS = ServiceIdentity("tutorial", "tasks", 1)
AUDIT = ServiceIdentity("tutorial", "audit", 1)


class Task(msgspec.Struct, frozen=True):
    """Public task representation returned by HTTP and RPC."""

    id: int
    title: str


class CreateTaskV1(msgspec.Struct, forbid_unknown_fields=True):
    """Version 1 task creation request."""

    title: str


class GetTaskV1(msgspec.Struct, forbid_unknown_fields=True):
    """Version 1 task lookup request."""

    task_id: int


class ListTasksV1(msgspec.Struct, forbid_unknown_fields=True):
    """Empty version 1 task-list request."""


class TaskCreatedV1(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Version 1 integration event published by the task service."""

    event_id: UUID
    task_id: int
    title: str


@service_contract(TASKS)
class TaskService(Protocol):
    """Finite-deadline RPC contract exposed by the task service."""

    @rpc_call("create-task", payload=CreateTaskV1, timeout=2.0)
    async def create_task(self, title: str) -> Task: ...

    @rpc_call("list-tasks", payload=ListTasksV1, timeout=2.0)
    async def list_tasks(self) -> list[Task]: ...

    @rpc_call("get-task", payload=GetTaskV1, timeout=2.0)
    async def get_task(self, task_id: int) -> Task: ...


__all__ = [
    "AUDIT",
    "TASKS",
    "CreateTaskV1",
    "GetTaskV1",
    "ListTasksV1",
    "Task",
    "TaskCreatedV1",
    "TaskService",
]
