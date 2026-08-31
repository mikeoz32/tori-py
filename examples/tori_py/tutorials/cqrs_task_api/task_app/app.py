"""Module composition and ASGI bootstrap for the tutorial application."""

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

from .handlers import (
    AuditTaskCreated,
    CreateTaskHandler,
    GetTaskHandler,
    ListTasksHandler,
    ProjectTaskCreated,
)
from .http import TaskController, TaskErrorFilter
from .state import TaskAuditLog, TaskProjection, TaskRepository

cqrs_module = CqrsModule.for_root(global_=True)


@module(
    providers=[
        ClassProvider(TaskRepository),
        ClassProvider(TaskProjection),
        ClassProvider(TaskAuditLog),
        CreateTaskHandler,
        ProjectTaskCreated,
        AuditTaskCreated,
        GetTaskHandler,
        ListTasksHandler,
    ],
    controllers=[TaskController],
)
class TasksModule:
    pass


@module(
    imports=[cqrs_module, TasksModule],
    providers=[
        ValueProvider("validation", MsgspecValidationPipe()),
        ValueProvider("task-errors", TaskErrorFilter()),
    ],
)
class AppModule:
    pass


pipeline_options = PipelineOptions(
    pipes=("validation",),
    filters=("task-errors",),
)


async def create_application() -> NestApplication:
    return await NestApplication.create(
        AppModule,
        pipeline=pipeline_options,
        adapter=StarletteAdapter(),
    )


application = asgi(create_application)
