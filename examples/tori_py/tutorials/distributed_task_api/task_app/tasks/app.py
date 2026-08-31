"""Task service RPC boundary and production composition root."""

from __future__ import annotations

import asyncio
from typing import Annotated

from tori_py import ClassProvider, NestApplication, controller, module
from tori_py_cqrs import CqrsModule
from tori_py_microservices import (
    MicroservicesModule,
    Payload,
    PublicRpcError,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    rpc,
)

from ..contracts import (
    TASKS,
    CreateTaskV1,
    GetTaskV1,
    ListTasksV1,
    Task,
    TaskService,
)
from ..infrastructure import rabbitmq_url, serve
from .handlers import (
    CountTaskCreated,
    CreateTaskHandler,
    GetTaskHandler,
    ListTasksHandler,
)
from .models import TaskNotFound, TaskTitleInvalid
from .services import TaskApplicationService
from .state import TaskMetrics, TaskRepository


@controller()
class TaskRpcController:
    def __init__(self, tasks: TaskApplicationService) -> None:
        self._tasks = tasks

    @rpc(TaskService.create_task)
    async def create_task(
        self,
        payload: Annotated[CreateTaskV1, Payload()],
    ) -> Task:
        try:
            return await self._tasks.create(payload.title)
        except TaskTitleInvalid as error:
            raise PublicRpcError(
                "invalid_request",
                "After trimming, the task title must contain 1-120 characters.",
            ) from error

    @rpc(TaskService.list_tasks)
    async def list_tasks(
        self,
        payload: Annotated[ListTasksV1, Payload()],
    ) -> list[Task]:
        del payload
        return await self._tasks.list_tasks()

    @rpc(TaskService.get_task)
    async def get_task(
        self,
        payload: Annotated[GetTaskV1, Payload()],
    ) -> Task:
        try:
            return await self._tasks.get(payload.task_id)
        except TaskNotFound as error:
            raise PublicRpcError("not_found", "Task was not found.") from error


task_transport = RabbitMqTransport()
task_rabbit = RabbitMqModule.for_root(
    RabbitMqOptions(
        rabbitmq_url(),
        connection_name="distributed-task-tasks",
    )
)
task_microservices = MicroservicesModule.for_root(
    TASKS,
    transport=task_transport,
    imports=(task_rabbit,),
)
task_cqrs = CqrsModule.for_root(global_=True)


@module(
    imports=(task_cqrs, task_microservices),
    providers=(
        ClassProvider(TaskRepository),
        ClassProvider(TaskMetrics),
        ClassProvider(TaskApplicationService),
        CreateTaskHandler,
        ListTasksHandler,
        GetTaskHandler,
        CountTaskCreated,
    ),
    controllers=(TaskRpcController,),
)
class TaskAppModule:
    """Composition root for the task-owning process."""


async def create_application() -> NestApplication:
    return await NestApplication.create(TaskAppModule)


async def run() -> None:
    await serve(create_application)


if __name__ == "__main__":
    asyncio.run(run())


__all__ = [
    "TaskAppModule",
    "TaskRpcController",
    "create_application",
    "task_rabbit",
    "task_transport",
]
