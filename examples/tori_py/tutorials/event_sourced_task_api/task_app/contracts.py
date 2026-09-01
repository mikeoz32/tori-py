"""Versioned RPC contracts shared by the four application roots."""

from __future__ import annotations

from typing import Protocol

import msgspec
from tori_py_microservices import ServiceIdentity, rpc_call, service_contract

TASK_COMMANDS = ServiceIdentity("tutorial", "task-commands", 1)
TASK_PROJECTION = ServiceIdentity("tutorial", "task-projection", 1)


class Task(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """The exact public task representation."""

    id: int
    title: str


class CreateTaskV1(msgspec.Struct, forbid_unknown_fields=True):
    title: str


class RenameTaskV1(msgspec.Struct, forbid_unknown_fields=True):
    task_id: int
    title: str


class GetTaskV1(msgspec.Struct, forbid_unknown_fields=True):
    task_id: int


class ListTasksV1(msgspec.Struct, forbid_unknown_fields=True):
    pass


@service_contract(TASK_COMMANDS)
class TaskCommandService(Protocol):
    """Finite-deadline command API owned by the event-sourced service."""

    @rpc_call("create-task", payload=CreateTaskV1, timeout=2.0)
    async def create_task(self, title: str) -> Task: ...

    @rpc_call("rename-task", payload=RenameTaskV1, timeout=2.0)
    async def rename_task(self, task_id: int, title: str) -> Task: ...


@service_contract(TASK_PROJECTION)
class TaskProjectionService(Protocol):
    """Finite-deadline query API owned by the projection service."""

    @rpc_call("list-tasks", payload=ListTasksV1, timeout=2.0)
    async def list_tasks(self) -> list[Task]: ...

    @rpc_call("get-task", payload=GetTaskV1, timeout=2.0)
    async def get_task(self, task_id: int) -> Task: ...


__all__ = [
    "TASK_COMMANDS",
    "TASK_PROJECTION",
    "CreateTaskV1",
    "GetTaskV1",
    "ListTasksV1",
    "RenameTaskV1",
    "Task",
    "TaskCommandService",
    "TaskProjectionService",
]
