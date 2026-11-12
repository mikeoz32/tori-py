"""Module composition and ASGI bootstrap for the Task API with task activity."""

from tori_py import (
    ClassProvider,
    NestApplication,
    PipelineOptions,
    ValueProvider,
    module,
)
from tori_py.http import MsgspecValidationPipe
from tori_py.starlette import StarletteAdapter, asgi

from .http import ActivityController, TaskController, TaskErrorFilter
from .projection import ActivityLog, ActivityProjection
from .services import TaskService
from .state import TaskRepository
from .streams import streams_module


@module(
    providers=[ClassProvider(TaskRepository)],
    exports=[TaskRepository],
)
class InfrastructureModule:
    pass


@module(
    imports=[InfrastructureModule],
    providers=[ClassProvider(TaskService)],
    controllers=[TaskController],
)
class TasksModule:
    pass


@module(
    providers=[ClassProvider(ActivityLog)],
    controllers=[ActivityProjection, ActivityController],
)
class ActivityModule:
    pass


def application_module() -> type[object]:
    """Build a root whose stream adapter and checkpoints belong to one application."""

    @module(
        imports=[streams_module(), TasksModule, ActivityModule],
        providers=[
            ValueProvider("validation", MsgspecValidationPipe()),
            ValueProvider("task-errors", TaskErrorFilter()),
        ],
    )
    class AppModule:
        pass

    return AppModule


PIPELINE = PipelineOptions(pipes=("validation",), filters=("task-errors",))


async def create_application() -> NestApplication:
    return await NestApplication.create(
        application_module(),
        adapter=StarletteAdapter(),
        pipeline=PIPELINE,
    )


application = asgi(create_application)
