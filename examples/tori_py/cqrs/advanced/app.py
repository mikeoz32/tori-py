"""Advanced event-driven Task API using ToriPy and tori-py-cqrs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import TracebackType
from typing import Annotated

import msgspec
from tori_py import (
    Body,
    ClassProvider,
    Context,
    Header,
    NestApplication,
    Path,
    PipelineOptions,
    PipelineResult,
    Scope,
    ValueProvider,
    controller,
    get,
    module,
    post,
    status,
)
from tori_py.http import MsgspecValidationPipe
from tori_py.starlette import RequestContext, StarletteAdapter, asgi
from tori_py.starlette.errors import problem_response
from tori_py_cqrs import CqrsModule, command_handler, event_handler, query_handler
from tori_py_cqrs_core import (
    Command,
    CommandBus,
    Event,
    EventBus,
    Query,
    QueryBus,
)


class Task(msgspec.Struct, frozen=True):
    """Task returned by the write side and materialized by the read side."""

    id: int
    title: str
    created_by: str


class CreateTaskBody(msgspec.Struct):
    """Validated HTTP request body."""

    title: str


class AuditEntry(msgspec.Struct, frozen=True):
    """Independent event-handler output."""

    task_id: int
    actor: str


class TaskTitleInvalid(Exception):
    """Raised when command validation rejects a task title."""


class TaskNotFound(Exception):
    """Raised when the read projection does not contain a requested task."""


@dataclass(frozen=True, slots=True)
class CreateTask(Command[Task]):
    title: str
    actor: str


@dataclass(frozen=True, slots=True)
class GetTask(Query[Task]):
    task_id: int


@dataclass(frozen=True, slots=True)
class ListTasks(Query[list[Task]]):
    pass


@dataclass(frozen=True, slots=True)
class TaskCreated(Event):
    task: Task


class TaskRepository:
    """Singleton write model; a real application would use durable storage."""

    def __init__(self) -> None:
        self._tasks: dict[int, Task] = {}
        self._next_id = 1

    def create(self, title: str, actor: str) -> Task:
        task = Task(self._next_id, title, actor)
        self._tasks[task.id] = task
        self._next_id += 1
        return task


class TaskProjection:
    """Singleton in-process read model updated only by domain events."""

    def __init__(self) -> None:
        self._tasks: dict[int, Task] = {}
        self._changed = asyncio.Condition()

    async def apply(self, event: TaskCreated) -> None:
        async with self._changed:
            self._tasks[event.task.id] = event.task
            self._changed.notify_all()

    def get(self, task_id: int) -> Task:
        try:
            return self._tasks[task_id]
        except KeyError as error:
            raise TaskNotFound from error

    def all(self) -> list[Task]:
        return [self._tasks[task_id] for task_id in sorted(self._tasks)]

    async def wait_for_count(self, count: int, *, timeout: float) -> None:
        async with self._changed:
            await asyncio.wait_for(
                self._changed.wait_for(lambda: len(self._tasks) >= count),
                timeout,
            )


class AuditLog:
    """A second event-handler target independent from the read projection."""

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []
        self._changed = asyncio.Condition()

    async def record(self, entry: AuditEntry) -> None:
        async with self._changed:
            self.entries.append(entry)
            self._changed.notify_all()

    async def wait_for_count(self, count: int, *, timeout: float) -> None:
        async with self._changed:
            await asyncio.wait_for(
                self._changed.wait_for(lambda: len(self.entries) >= count),
                timeout,
            )


class ScopeMetrics:
    """Makes scoped handler/resource behavior observable in the example test."""

    def __init__(self) -> None:
        self.command_scope_entries = 0
        self.command_scope_exits = 0
        self.command_handler_constructions = 0
        self.command_handler_sequences: list[int] = []
        self.query_handler_constructions = 0
        self.projection_handler_constructions = 0


class CommandScope:
    """Request-scoped managed resource created for each command invocation."""

    def __init__(self, metrics: ScopeMetrics) -> None:
        self._metrics = metrics
        self.sequence = 0

    async def __aenter__(self) -> CommandScope:
        self._metrics.command_scope_entries += 1
        self.sequence = self._metrics.command_scope_entries
        return self

    async def __aexit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del error_type, error, traceback
        self._metrics.command_scope_exits += 1


@command_handler(CreateTask, scope=Scope.REQUEST)
class CreateTaskHandler:
    """Request-scoped write handler discovered from its provider metadata."""

    def __init__(
        self,
        repository: TaskRepository,
        events: EventBus,
        command_scope: CommandScope,
        metrics: ScopeMetrics,
    ) -> None:
        self._repository = repository
        self._events = events
        self._scope = command_scope
        self._metrics = metrics
        metrics.command_handler_constructions += 1
        self._sequence = metrics.command_handler_constructions

    async def handle(self, command: CreateTask) -> Task:
        title = command.title.strip()
        if not title or len(title) > 120:
            raise TaskTitleInvalid
        self._metrics.command_handler_sequences.append(self._sequence)
        assert self._scope.sequence > 0
        task = self._repository.create(title, command.actor)
        await self._events.publish(TaskCreated(task))
        return task


@event_handler(TaskCreated, scope=Scope.REQUEST)
class ProjectTaskCreated:
    """Request-scoped event handler maintaining the query projection."""

    def __init__(self, projection: TaskProjection, metrics: ScopeMetrics) -> None:
        self._projection = projection
        metrics.projection_handler_constructions += 1

    async def handle(self, event: TaskCreated) -> None:
        await self._projection.apply(event)


@event_handler(TaskCreated, scope=Scope.TRANSIENT)
class AuditTaskCreated:
    """Transient event handler demonstrating independent fan-out."""

    def __init__(self, audit: AuditLog) -> None:
        self._audit = audit

    async def handle(self, event: TaskCreated) -> None:
        await self._audit.record(AuditEntry(event.task.id, event.task.created_by))


@query_handler(GetTask, scope=Scope.TRANSIENT)
class GetTaskHandler:
    """Transient query handler reading only the projection."""

    def __init__(self, projection: TaskProjection, metrics: ScopeMetrics) -> None:
        self._projection = projection
        metrics.query_handler_constructions += 1

    async def handle(self, query: GetTask) -> Task:
        return self._projection.get(query.task_id)


@query_handler(ListTasks, scope=Scope.TRANSIENT)
class ListTasksHandler:
    """Separate transient query handler for collection reads."""

    def __init__(self, projection: TaskProjection, metrics: ScopeMetrics) -> None:
        self._projection = projection
        metrics.query_handler_constructions += 1

    async def handle(self, query: ListTasks) -> list[Task]:
        return self._projection.all()


@controller("/tasks")
class TaskController:
    """Thin HTTP adapter dispatching commands and queries through buses."""

    def __init__(self, commands: CommandBus, queries: QueryBus) -> None:
        self._commands = commands
        self._queries = queries

    @post("")
    @status(202)
    async def create(
        self,
        body: Annotated[CreateTaskBody, Body()],
        actor: Annotated[str, Header("x-actor")],
        context: Annotated[RequestContext, Context()],
    ) -> dict[str, object]:
        task = await self._commands.execute(CreateTask(body.title, actor))
        return {
            "task": task,
            "projection": "asynchronous-in-process",
            "request_id": context.request_id,
        }

    @get("")
    async def list(self) -> list[Task]:
        return await self._queries.execute(ListTasks())

    @get("/{task_id}")
    async def get_one(
        self,
        task_id: Annotated[int, Path("task_id")],
    ) -> Task:
        return await self._queries.execute(GetTask(task_id))


class TaskErrorFilter:
    """Translate domain/query failures into HTTP Problem Details responses."""

    async def catch(
        self,
        error: Exception,
        context: RequestContext,
    ) -> PipelineResult:
        if isinstance(error, TaskTitleInvalid):
            return PipelineResult.from_response(
                problem_response(
                    400,
                    "Task title must contain 1-120 non-whitespace characters.",
                    request=context.request,
                )
            )
        if isinstance(error, TaskNotFound):
            return PipelineResult.from_response(
                problem_response(404, "Task was not found.", request=context.request)
            )
        raise error


cqrs_module = CqrsModule.for_root(global_=True)


@module(
    providers=[
        ClassProvider(TaskRepository),
        ClassProvider(TaskProjection),
        ClassProvider(AuditLog),
        ClassProvider(ScopeMetrics),
        ClassProvider(CommandScope, scope=Scope.REQUEST),
        CreateTaskHandler,
        ProjectTaskCreated,
        AuditTaskCreated,
        GetTaskHandler,
        ListTasksHandler,
    ],
    controllers=[TaskController],
)
class TasksModule:
    """Feature module; CQRS handlers remain private and are registered once."""


@module(
    imports=[cqrs_module, TasksModule],
    providers=[
        ValueProvider("validation", MsgspecValidationPipe()),
        ValueProvider("task-errors", TaskErrorFilter()),
    ],
)
class AppModule:
    """Root module composing HTTP, CQRS infrastructure, and task providers."""


pipeline_options = PipelineOptions(
    pipes=("validation",),
    filters=("task-errors",),
)


async def create_application() -> NestApplication:
    """Create an unstarted application for CLI or ASGI lifespan ownership."""

    return await NestApplication.create(
        AppModule,
        pipeline=pipeline_options,
        adapter=StarletteAdapter(),
    )


application = asgi(create_application)
