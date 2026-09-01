"""Event-sourced task command RPC service and production composition root."""

from __future__ import annotations

import asyncio
from typing import Annotated

from tori_py import ClassProvider, NestApplication, controller, module
from tori_py_cqrs import CqrsModule
from tori_py_cqrs_event_sourcing import (
    ConfirmedCommandFinalizationError,
    ConfirmedNonCommitFinalizationError,
    CqrsEventSourcingModule,
    CqrsEventSourcingOptions,
    IndeterminateCommandFinalizationError,
)
from tori_py_cqrs_event_sourcing_core import (
    AggregateNotFoundError,
    CommitResultMismatchError,
    IndeterminateCommitError,
    InMemoryEventStore,
    OptimisticConcurrencyError,
)
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
)
from tori_py_persistent_streams_rabbitmq import RabbitMqPersistentStreamsModule

from ..contracts import (
    TASK_COMMANDS,
    CreateTaskV1,
    RenameTaskV1,
    Task,
    TaskCommandService,
)
from ..infrastructure import (
    rabbitmq_amqp_url,
    rabbitmq_stream_options,
    serve,
)
from ..streams import task_event_binding
from .domain import TaskTitleInvalid
from .handlers import CreateTaskHandler, RenameTaskHandler
from .relay import (
    EVENT_SOURCING_KEY,
    RelayGate,
    RelayPublicationError,
    RelayUnavailable,
    TaskEventRelay,
)
from .repository import TaskRepository
from .schemas import TASK_SCHEMAS
from .services import TaskApplicationService
from .state import TaskIdSequence


@controller()
class TaskRpcController:
    def __init__(self, tasks: TaskApplicationService) -> None:
        self._tasks = tasks

    @rpc(TaskCommandService.create_task)
    async def create_task(
        self,
        payload: Annotated[CreateTaskV1, Payload()],
    ) -> Task:
        try:
            return await self._tasks.create(payload.title)
        except (RelayUnavailable, RelayPublicationError) as error:
            raise _relay_unavailable(error) from error
        except TaskTitleInvalid as error:
            raise _invalid_title(error) from error
        except OptimisticConcurrencyError as error:
            raise _conflict(error) from error
        except ConfirmedCommandFinalizationError as error:
            raise _confirmed_finalization(error) from error
        except (
            IndeterminateCommandFinalizationError,
            CommitResultMismatchError,
            IndeterminateCommitError,
        ) as error:
            raise _indeterminate(error) from error
        except ConfirmedNonCommitFinalizationError as error:
            raise _non_commit_finalization(error) from error

    @rpc(TaskCommandService.rename_task)
    async def rename_task(
        self,
        payload: Annotated[RenameTaskV1, Payload()],
    ) -> Task:
        try:
            return await self._tasks.rename(payload.task_id, payload.title)
        except (RelayUnavailable, RelayPublicationError) as error:
            raise _relay_unavailable(error) from error
        except TaskTitleInvalid as error:
            raise _invalid_title(error) from error
        except AggregateNotFoundError as error:
            raise PublicRpcError("not_found", "Task was not found.") from error
        except OptimisticConcurrencyError as error:
            raise _conflict(error) from error
        except ConfirmedCommandFinalizationError as error:
            raise _confirmed_finalization(error) from error
        except (
            IndeterminateCommandFinalizationError,
            CommitResultMismatchError,
            IndeterminateCommitError,
        ) as error:
            raise _indeterminate(error) from error
        except ConfirmedNonCommitFinalizationError as error:
            raise _non_commit_finalization(error) from error


def _invalid_title(error: BaseException) -> PublicRpcError:
    del error
    return PublicRpcError(
        "invalid_request",
        "After trimming, the task title must contain 1-120 characters.",
    )


def _relay_unavailable(error: BaseException) -> PublicRpcError:
    del error
    return PublicRpcError(
        "relay_unavailable",
        "Task event relay is unavailable.",
    )


def _conflict(error: BaseException) -> PublicRpcError:
    del error
    return PublicRpcError(
        "conflict",
        "Task was changed by another request.",
        retryable=True,
    )


def _confirmed_finalization(error: BaseException) -> PublicRpcError:
    del error
    return PublicRpcError(
        "command_committed_finalization_failed",
        "The task command committed, but command finalization failed.",
    )


def _indeterminate(error: BaseException) -> PublicRpcError:
    del error
    return PublicRpcError(
        "command_outcome_unknown",
        "The task command outcome is unknown and may have committed.",
    )


def _non_commit_finalization(error: BaseException) -> PublicRpcError:
    del error
    return PublicRpcError(
        "command_finalization_failed",
        "The task command did not commit, but command finalization failed.",
    )


@module(
    providers=(ClassProvider(InMemoryEventStore),),
    exports=(InMemoryEventStore,),
)
class TaskPersistenceModule:
    """Own the command service's in-memory event store."""


task_event_sourcing = CqrsEventSourcingModule.for_root(
    CqrsEventSourcingOptions(
        store=InMemoryEventStore,
        schemas=TASK_SCHEMAS,
    ),
    imports=(TaskPersistenceModule,),
    key=EVENT_SOURCING_KEY,
)
task_repositories = CqrsEventSourcingModule.for_feature(
    (TaskRepository,),
    root_key=EVENT_SOURCING_KEY,
    key="task-model",
)
task_cqrs = CqrsModule.for_root(global_=True)

task_transport = RabbitMqTransport()
task_rabbit = RabbitMqModule.for_root(
    RabbitMqOptions(
        rabbitmq_amqp_url(),
        connection_name="event-sourced-task-commands",
    )
)
task_microservices = MicroservicesModule.for_root(
    TASK_COMMANDS,
    transport=task_transport,
    imports=(task_rabbit,),
)

task_stream_adapter = RabbitMqPersistentStreamsModule.for_root(
    rabbitmq_stream_options("event-sourced-task-relay")
)
task_streams = PersistentStreamsModule.for_root(
    PersistentStreamsOptions(
        bindings=(task_event_binding(),),
        runtime=PersistentStreamsRuntimeOptions(
            owner_id="task-command-relay-v1",
        ),
    ),
    imports=(task_stream_adapter,),
)


@module(
    imports=(
        task_event_sourcing,
        task_repositories,
        task_cqrs,
        task_microservices,
        task_streams,
    ),
    providers=(
        ClassProvider(TaskIdSequence),
        ClassProvider(RelayGate),
        ClassProvider(TaskEventRelay),
        ClassProvider(TaskApplicationService),
        CreateTaskHandler,
        RenameTaskHandler,
    ),
    controllers=(TaskRpcController,),
    exports=(RelayGate, TaskEventRelay),
)
class TaskAppModule:
    """The task command service's independent application root."""


async def create_application() -> NestApplication:
    return await NestApplication.create(TaskAppModule)


async def run() -> None:
    await serve(create_application)


if __name__ == "__main__":
    asyncio.run(run())


__all__ = [
    "TaskAppModule",
    "TaskPersistenceModule",
    "TaskRpcController",
    "create_application",
    "task_rabbit",
    "task_stream_adapter",
    "task_transport",
]
