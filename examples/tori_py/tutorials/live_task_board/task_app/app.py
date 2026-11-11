"""Module composition and ASGI bootstrap for the tutorial application."""

import os

from tori_py import (
    ClassProvider,
    NestApplication,
    ValueProvider,
    module,
)
from tori_py.http import MsgspecValidationPipe
from tori_py.starlette import StarletteAdapter, asgi
from tori_py_cqrs import CqrsModule
from tori_py_liveview import LiveViewModule, LiveViewOptions
from tori_py_liveview_ui import LiveViewUiModule

from .feed import AnnounceTaskCreated, TaskBoardFeed
from .handlers import (
    AuditTaskCreated,
    CountTaskCreated,
    CreateTaskHandler,
    GetTaskHandler,
    ListTasksHandler,
)
from .http import TaskController, TaskErrorFilter
from .live import TaskBoardLive
from .observers import TaskAuditLog, TaskMetrics
from .services import TaskService
from .state import TaskRepository

# Local development only. Deployments set TASK_BOARD_SECRET.
DEVELOPMENT_SECRET = "task-board-development-secret-change-me"

cqrs_module = CqrsModule.for_root(global_=True)


@module(
    providers=[ClassProvider(TaskRepository)],
    exports=[TaskRepository],
)
class InfrastructureModule:
    pass


@module(
    imports=[InfrastructureModule],
    providers=[
        ClassProvider(TaskService),
        ClassProvider(TaskAuditLog),
        ClassProvider(TaskMetrics),
        ClassProvider(TaskBoardFeed),
        CreateTaskHandler,
        GetTaskHandler,
        ListTasksHandler,
        AuditTaskCreated,
        CountTaskCreated,
        AnnounceTaskCreated,
    ],
    controllers=[TaskController],
    exports=[TaskBoardFeed],
)
class TasksModule:
    pass


liveview_module = LiveViewModule.for_root(
    LiveViewOptions(secret=os.environ.get("TASK_BOARD_SECRET", DEVELOPMENT_SECRET)),
    pages=[TaskBoardLive],
    imports=[TasksModule],
)


@module(
    imports=[cqrs_module, TasksModule, liveview_module, LiveViewUiModule.for_root()],
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
