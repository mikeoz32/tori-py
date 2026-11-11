"""Module composition and ASGI bootstrap for the Task API with a live feed."""

from tori_py import (
    ClassProvider,
    FactoryProvider,
    NestApplication,
    Scope,
    ValueProvider,
    module,
)
from tori_py.http import MsgspecValidationPipe
from tori_py.starlette import StarletteAdapter, asgi

from .feed import TaskFeed
from .http import TaskController, TaskErrorFilter
from .live import TASK_WAKEUP, TaskFeedGateway, subscribe
from .services import TaskService
from .state import TaskRepository


@module(
    providers=[ClassProvider(TaskRepository), ClassProvider(TaskFeed)],
    exports=[TaskRepository, TaskFeed],
)
class InfrastructureModule:
    pass


@module(
    imports=[InfrastructureModule],
    providers=[
        ClassProvider(TaskService),
        FactoryProvider(TASK_WAKEUP, subscribe, scope=Scope.REQUEST),
        TaskFeedGateway,
    ],
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
