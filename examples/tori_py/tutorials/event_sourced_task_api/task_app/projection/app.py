"""Persistent projection consumer, query RPC API, and production root."""

from __future__ import annotations

import asyncio
from typing import Annotated

from tori_py import ClassProvider, NestApplication, controller, module
from tori_py_microservices import (
    MicroservicesModule,
    Payload,
    PublicRpcError,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    rpc,
)
from tori_py_persistent_streams import (
    PersistentStreamsModule,
    PersistentStreamsOptions,
    PersistentStreamsRuntimeOptions,
    StreamPayload,
    stream_handler,
)
from tori_py_persistent_streams_core import InMemoryCheckpointStore
from tori_py_persistent_streams_rabbitmq import RabbitMqPersistentStreamsModule

from ..contracts import (
    TASK_PROJECTION,
    GetTaskV1,
    ListTasksV1,
    Task,
    TaskProjectionService,
)
from ..infrastructure import (
    rabbitmq_amqp_url,
    rabbitmq_stream_options,
    serve,
)
from ..streams import TASK_EVENTS_ALIAS, TaskEventRecordV1, task_event_binding
from .state import (
    ProjectionUnavailable,
    TaskProjectionMiss,
    TaskProjectionState,
)

PROJECTION_GROUP = "task-projection-v1"
PROJECTION_CHECKPOINTS = InMemoryCheckpointStore()


@controller()
class TaskProjectionStreamController:
    def __init__(self, state: TaskProjectionState) -> None:
        self._state = state

    @stream_handler(stream=TASK_EVENTS_ALIAS, consumer_group=PROJECTION_GROUP)
    async def project(
        self,
        record: Annotated[TaskEventRecordV1, StreamPayload()],
    ) -> None:
        await self._state.apply(record)


@controller()
class TaskProjectionRpcController:
    def __init__(self, state: TaskProjectionState) -> None:
        self._state = state

    @rpc(TaskProjectionService.list_tasks)
    async def list_tasks(
        self,
        payload: Annotated[ListTasksV1, Payload()],
    ) -> list[Task]:
        del payload
        try:
            return self._state.all()
        except ProjectionUnavailable as error:
            raise _projection_unavailable(error) from error

    @rpc(TaskProjectionService.get_task)
    async def get_task(
        self,
        payload: Annotated[GetTaskV1, Payload()],
    ) -> Task:
        try:
            return self._state.get(payload.task_id)
        except TaskProjectionMiss as error:
            raise PublicRpcError("not_found", "Task was not found.") from error
        except ProjectionUnavailable as error:
            raise _projection_unavailable(error) from error


def _projection_unavailable(error: BaseException) -> PublicRpcError:
    del error
    return PublicRpcError(
        "projection_unavailable",
        "Task projection is unavailable.",
        retryable=True,
    )


projection_transport = RabbitMqTransport()
projection_rabbit = RabbitMqModule.for_root(
    RabbitMqOptions(
        rabbitmq_amqp_url(),
        connection_name="event-sourced-task-projection-rpc",
    )
)
projection_microservices = MicroservicesModule.for_root(
    TASK_PROJECTION,
    transport=projection_transport,
    imports=(projection_rabbit,),
)

projection_stream_adapter = RabbitMqPersistentStreamsModule.for_root(
    rabbitmq_stream_options("event-sourced-task-projection-stream")
)
projection_streams = PersistentStreamsModule.for_root(
    PersistentStreamsOptions(
        bindings=(
            task_event_binding(
                PROJECTION_CHECKPOINTS,
                checkpoint_identity="task-projection-v1-memory",
            ),
        ),
        runtime=PersistentStreamsRuntimeOptions(
            owner_id="task-projection-v1",
            single_instance_consumer_groups=True,
        ),
    ),
    imports=(projection_stream_adapter,),
)


@module(
    imports=(projection_microservices, projection_streams),
    providers=(ClassProvider(TaskProjectionState),),
    controllers=(TaskProjectionStreamController, TaskProjectionRpcController),
    exports=(TaskProjectionState,),
)
class ProjectionAppModule:
    """The projection service's independent application root."""


async def create_application() -> NestApplication:
    return await NestApplication.create(ProjectionAppModule)


async def run() -> None:
    await serve(create_application)


if __name__ == "__main__":
    asyncio.run(run())


__all__ = [
    "PROJECTION_CHECKPOINTS",
    "PROJECTION_GROUP",
    "ProjectionAppModule",
    "TaskProjectionRpcController",
    "TaskProjectionStreamController",
    "create_application",
    "projection_rabbit",
    "projection_stream_adapter",
    "projection_transport",
]
