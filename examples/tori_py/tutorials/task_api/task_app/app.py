"""Module composition and ASGI bootstrap for the ordinary Task API."""

from tori_py import ClassProvider, NestApplication, ValueProvider, module
from tori_py.http import MsgspecValidationPipe
from tori_py.starlette import StarletteAdapter, asgi

from .http import TaskController, TaskErrorFilter
from .services import TaskService
from .state import TaskRepository


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
    imports=[TasksModule],
    providers=[
        ValueProvider("validation", MsgspecValidationPipe()),
        ValueProvider("task-errors", TaskErrorFilter()),
    ],
)
class AppModule:
    pass


async def create_application() -> NestApplication:
    app = await NestApplication.create(AppModule, adapter=StarletteAdapter())
    app.use_global_pipe("validation")
    app.use_global_filter("task-errors")
    return app


application = asgi(create_application)
