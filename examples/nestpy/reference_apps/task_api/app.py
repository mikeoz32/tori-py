"""A small composed HTTP application using Nestpy's public v1 APIs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path as FilePath
from typing import Annotated

import msgspec
from nestpy import (
    Body,
    ClassProvider,
    Context,
    FactoryProvider,
    Inject,
    Logger,
    Path,
    PipelineResult,
    Scope,
    StarletteOptions,
    ValueProvider,
    controller,
    get,
    module,
    post,
    status,
    use_guards,
)
from nestpy.logging import LoggingModule
from nestpy.settings import SettingsModule, SettingsOptions
from nestpy.starlette import (
    MsgspecValidationPipe,
    NestApplication,
    RequestContext,
    asgi,
)
from nestpy.starlette.errors import problem_response


class TaskApiSettings(msgspec.Struct):
    """Configuration for the Task API reference application."""

    max_title_length: int = 120


class CreateTask(msgspec.Struct):
    """Validated payload for creating one task."""

    title: str


class Task(msgspec.Struct, frozen=True):
    """A persisted task returned by the HTTP API."""

    id: int
    title: str


class TaskNotFound(Exception):
    """Raised when a requested task is absent from the repository."""


class TaskTitleInvalid(Exception):
    """Raised when a title is empty or exceeds configured limits."""


class TaskRepository:
    """In-memory singleton repository with deterministic lifecycle cleanup."""

    def __init__(self) -> None:
        self._tasks: dict[int, Task] = {}
        self._next_id = 1
        self.closed = False

    def create(self, title: str) -> Task:
        self._ensure_open()
        task = Task(self._next_id, title)
        self._tasks[task.id] = task
        self._next_id += 1
        return task

    def all(self) -> list[Task]:
        self._ensure_open()
        return list(self._tasks.values())

    def get(self, task_id: int) -> Task:
        self._ensure_open()
        try:
            return self._tasks[task_id]
        except KeyError as error:
            raise TaskNotFound from error

    async def on_module_destroy(self) -> None:
        self.closed = True
        self._tasks.clear()

    def _ensure_open(self) -> None:
        if self.closed:
            raise RuntimeError("task repository is closed")


class TaskService:
    """Application service separating HTTP concerns from storage behavior."""

    def __init__(
        self,
        repository: TaskRepository,
        settings: TaskApiSettings,
        logger: Logger,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._logger = logger

    def create(self, command: CreateTask) -> Task:
        title = command.title.strip()
        if not title or len(title) > self._settings.max_title_length:
            raise TaskTitleInvalid
        task = self._repository.create(title)
        self._logger.info("Task created", task_id=task.id)
        return task

    def all(self) -> list[Task]:
        return self._repository.all()

    def get(self, task_id: int) -> Task:
        return self._repository.get(task_id)


@dataclass(frozen=True, slots=True)
class RequestMarker:
    """Request-scoped value injected only for the lifetime of one request."""

    request_id: str


class TaskWriteGuard:
    """Example policy boundary; production applications supply a real policy."""

    async def can_activate(self, context: RequestContext) -> bool:
        return context.headers.get("x-task-write") == "allow"


class TaskErrorFilter:
    """Map task-domain exceptions to reusable HTTP Problem Details failures."""

    async def catch(
        self,
        error: Exception,
        context: RequestContext,
    ) -> PipelineResult:
        if isinstance(error, TaskNotFound):
            return PipelineResult.from_response(
                problem_response(
                    404,
                    "Task was not found.",
                    request=context.request,
                )
            )
        if isinstance(error, TaskTitleInvalid):
            return PipelineResult.from_response(
                problem_response(
                    400,
                    "Task title is invalid.",
                    request=context.request,
                )
            )
        raise error


@controller("/tasks")
class TaskController:
    """HTTP controller with raw bindings converted by the global validation pipe."""

    def __init__(self, tasks: TaskService) -> None:
        self._tasks = tasks

    @get("")
    async def list(self) -> list[Task]:
        return self._tasks.all()

    @post("")
    @status(201)
    @use_guards("task-write")
    async def create(
        self,
        command: Annotated[CreateTask, Body()],
        marker: Annotated[RequestMarker, Inject(RequestMarker)],
        context: Annotated[RequestContext, Context()],
    ) -> dict[str, object]:
        task = self._tasks.create(command)
        return {
            "task": task,
            "marker": marker.request_id,
            "request_id": context.request_id,
        }

    @get("/{task_id}")
    async def get_one(
        self,
        task_id: Annotated[int, Path("task_id")],
    ) -> Task:
        return self._tasks.get(task_id)


settings_module = SettingsModule.for_root(
    SettingsOptions(model=TaskApiSettings, base_dir=FilePath(__file__).parent),
    global_=True,
)
logging_module = LoggingModule.for_root(application="task-api")


@module(
    providers=[ClassProvider(TaskRepository)],
    exports=[TaskRepository],
)
class InfrastructureModule:
    """Owns singleton persistence-like resources."""


@module(
    imports=[InfrastructureModule],
    providers=[
        ClassProvider(TaskService),
        ValueProvider("task-write", TaskWriteGuard()),
        FactoryProvider(
            RequestMarker,
            lambda: RequestMarker("request-scope"),
            scope=Scope.REQUEST,
        ),
    ],
    controllers=[TaskController],
)
class TasksModule:
    """Owns task use cases and its HTTP controller."""


@module(
    imports=[settings_module, logging_module, InfrastructureModule, TasksModule],
    providers=[
        ValueProvider("validation", MsgspecValidationPipe()),
        ValueProvider("task-errors", TaskErrorFilter()),
    ],
    exports=[TaskRepository],
)
class AppModule:
    """Root composition module for the reference application."""


async def create_application() -> NestApplication:
    """Create an unstarted Task API for ASGI lifespan ownership."""

    return await NestApplication.create(
        AppModule,
        http=StarletteOptions(
            pipes=("validation",),
            filters=("task-errors",),
        ),
    )


application = asgi(create_application)
