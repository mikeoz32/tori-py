"""Module composition and ASGI bootstrap for the SQLAlchemy Task API."""

from tori_py import (
    ClassProvider,
    NestApplication,
    PipelineOptions,
    ValueProvider,
    module,
)
from tori_py.http import MsgspecValidationPipe
from tori_py.starlette import StarletteAdapter, asgi

from .database import database
from .http import TaskController, TaskErrorFilter
from .services import TaskService
from .state import task_persistence


@module(
    imports=[task_persistence],
    providers=[ClassProvider(TaskService)],
    controllers=[TaskController],
)
class TasksModule:
    pass


@module(
    imports=[database, TasksModule],
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
