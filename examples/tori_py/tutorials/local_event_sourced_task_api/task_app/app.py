"""Module composition and ASGI bootstrap for the event-sourced Task API."""

from tori_py import (
    ClassProvider,
    NestApplication,
    PipelineOptions,
    ValueProvider,
    module,
)
from tori_py.http import MsgspecValidationPipe
from tori_py.starlette import StarletteAdapter, asgi
from tori_py_cqrs import CqrsModule
from tori_py_cqrs_event_sourcing import (
    CqrsEventSourcingModule,
    CqrsEventSourcingOptions,
)
from tori_py_cqrs_event_sourcing_core import InMemoryEventStore

from .handlers import (
    CreateTaskHandler,
    GetTaskHandler,
    ListTasksHandler,
    RenameTaskHandler,
)
from .http import TaskController, TaskErrorFilter
from .projection import TaskProjection
from .reconciliation import ReconciliationLog
from .schemas import TASK_SCHEMAS
from .state import EVENT_STORE_KEY, TaskIdSequence, TaskRepository


@module(
    providers=[ClassProvider(InMemoryEventStore)],
    exports=[InMemoryEventStore],
)
class PersistenceModule:
    pass


event_sourcing_root = CqrsEventSourcingModule.for_root(
    CqrsEventSourcingOptions(store=InMemoryEventStore, schemas=TASK_SCHEMAS),
    imports=[PersistenceModule],
    key=EVENT_STORE_KEY,
)
task_repositories = CqrsEventSourcingModule.for_feature(
    [TaskRepository],
    root_key=EVENT_STORE_KEY,
    key="task-model",
)
cqrs_module = CqrsModule.for_root(global_=True)


@module(
    imports=[task_repositories],
    providers=[
        ClassProvider(TaskIdSequence),
        ClassProvider(TaskProjection),
        ClassProvider(ReconciliationLog),
        CreateTaskHandler,
        RenameTaskHandler,
        GetTaskHandler,
        ListTasksHandler,
    ],
    controllers=[TaskController],
)
class TasksModule:
    pass


@module(
    imports=[event_sourcing_root, cqrs_module, TasksModule],
    providers=[
        ValueProvider("validation", MsgspecValidationPipe()),
        ValueProvider("task-errors", TaskErrorFilter()),
    ],
)
class AppModule:
    pass


PIPELINE = PipelineOptions(pipes=("validation",), filters=("task-errors",))


async def create_application() -> NestApplication:
    return await NestApplication.create(
        AppModule,
        adapter=StarletteAdapter(),
        pipeline=PIPELINE,
    )


application = asgi(create_application)
