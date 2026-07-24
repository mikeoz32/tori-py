"""A runnable Nestpy application using async SQLAlchemy without CQRS."""

from pathlib import Path as FilePath
from typing import Annotated

import msgspec
from nestpy import (
    Body,
    NestApplication,
    Path,
    PipelineResult,
    ValueProvider,
    controller,
    get,
    injectable,
    module,
    post,
    status,
)
from nestpy.http import MsgspecValidationPipe
from nestpy.settings import SettingsModule, SettingsOptions
from nestpy.starlette import RequestContext, StarletteAdapter, asgi
from nestpy.starlette.errors import problem_response
from nestpy_sqlalchemy import EntityManager, SqlAlchemyModule, SqlAlchemyOptions
from sqlalchemy import String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

MAX_DATABASE_TITLE_LENGTH = 120


class DatabaseSettings(msgspec.Struct, frozen=True):
    """Database configuration selected by settings and environment values."""

    url: str = "sqlite+aiosqlite:///sqlalchemy_tasks.db"
    echo: bool = False


class TaskApiSettings(msgspec.Struct, frozen=True):
    """Typed settings consumed by both persistence and application services."""

    database: DatabaseSettings = msgspec.field(default_factory=DatabaseSettings)
    max_title_length: int = MAX_DATABASE_TITLE_LENGTH

    def __post_init__(self) -> None:
        if not 1 <= self.max_title_length <= MAX_DATABASE_TITLE_LENGTH:
            raise ValueError(
                f"max_title_length must be between 1 and {MAX_DATABASE_TITLE_LENGTH}"
            )


class CreateTaskBody(msgspec.Struct, forbid_unknown_fields=True):
    """Validated request body for task creation."""

    title: str


class TaskResponse(msgspec.Struct, frozen=True):
    """Transport DTO returned instead of an ORM entity."""

    id: int
    title: str


class Base(DeclarativeBase):
    """Application-owned SQLAlchemy metadata root."""


class TaskRow(Base):
    """Infrastructure model kept out of the HTTP response surface."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(
        String(MAX_DATABASE_TITLE_LENGTH),
        unique=True,
    )


class TaskNotFound(Exception):
    """Raised when a requested task is absent."""


class TaskTitleInvalid(Exception):
    """Raised when a normalized title violates application rules."""


class TaskAlreadyExists(Exception):
    """Raised when the database rejects a duplicate title."""


def create_database_options(settings: TaskApiSettings) -> SqlAlchemyOptions:
    """Build SQLAlchemy options from a DI-resolved settings instance."""

    return SqlAlchemyOptions(
        url=settings.database.url,
        engine_options={
            "echo": settings.database.echo,
            "pool_pre_ping": True,
        },
    )


@injectable()
class SchemaInitializer:
    """Application-owned demo schema bootstrap, not an integration feature."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def on_module_init(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)


@injectable()
class TaskService:
    """Singleton application service over the singleton EntityManager."""

    def __init__(
        self,
        entities: EntityManager,
        settings: TaskApiSettings,
    ) -> None:
        self._entities = entities
        self._settings = settings

    async def create(self, body: CreateTaskBody) -> TaskResponse:
        title = body.title.strip()
        if not title or len(title) > self._settings.max_title_length:
            raise TaskTitleInvalid
        try:
            row = await self._entities.add(TaskRow(title=title))
        except IntegrityError as error:
            raise TaskAlreadyExists from error
        return _task_response(row)

    async def get(self, task_id: int) -> TaskResponse:
        row = await self._entities.get(TaskRow, task_id)
        if row is None:
            raise TaskNotFound
        return _task_response(row)

    async def all(self) -> list[TaskResponse]:
        rows = await self._entities.scalars(select(TaskRow).order_by(TaskRow.id))
        return [_task_response(row) for row in rows]


class TaskErrorFilter:
    """Map application failures to HTTP Problem Details responses."""

    async def catch(
        self,
        error: Exception,
        context: RequestContext,
    ) -> PipelineResult:
        match error:
            case TaskNotFound():
                return PipelineResult.from_response(
                    problem_response(
                        404,
                        "Task was not found.",
                        request=context.request,
                    )
                )
            case TaskTitleInvalid():
                return PipelineResult.from_response(
                    problem_response(
                        400,
                        "Task title is invalid.",
                        request=context.request,
                    )
                )
            case TaskAlreadyExists():
                return PipelineResult.from_response(
                    problem_response(
                        409,
                        "A task with this title already exists.",
                        title="Conflict",
                        request=context.request,
                    )
                )
            case _:
                raise error


@controller("/tasks")
class TaskController:
    """Singleton controller with a singleton application service."""

    def __init__(self, tasks: TaskService) -> None:
        self._tasks = tasks

    @get("")
    async def list_tasks(self) -> list[TaskResponse]:
        return await self._tasks.all()

    @post("")
    @status(201)
    async def create_task(
        self,
        body: Annotated[CreateTaskBody, Body()],
    ) -> TaskResponse:
        return await self._tasks.create(body)

    @get("/{task_id}")
    async def get_task(
        self,
        task_id: Annotated[int, Path("task_id")],
    ) -> TaskResponse:
        return await self._tasks.get(task_id)


def _task_response(row: TaskRow) -> TaskResponse:
    return TaskResponse(id=row.id, title=row.title)


settings_module = SettingsModule.for_root(
    SettingsOptions(
        model=TaskApiSettings,
        base_dir=FilePath(__file__).parent,
        env_prefix="SQLALCHEMY_TASK_API_",
    ),
    global_=True,
)

sqlalchemy_module = SqlAlchemyModule.for_root_async(
    imports=[settings_module],
    use_factory=create_database_options,
)


@module(
    imports=[sqlalchemy_module],
    providers=[SchemaInitializer],
    exports=[EntityManager],
)
class DatabaseModule:
    """Composes the integration and application-owned schema bootstrap."""


@module(
    imports=[DatabaseModule],
    providers=[TaskService],
    controllers=[TaskController],
)
class TasksModule:
    """Owns the task use case and HTTP transport."""


@module(
    imports=[settings_module, DatabaseModule, TasksModule],
    providers=[
        ValueProvider("validation", MsgspecValidationPipe()),
        ValueProvider("task-errors", TaskErrorFilter()),
    ],
)
class AppModule:
    """Root composition module without any CQRS dependency."""


async def create_application() -> NestApplication:
    """Create an unstarted application for CLI, ASGI, or tests."""

    app = await NestApplication.create(AppModule, adapter=StarletteAdapter())
    app.use_global_pipe("validation")
    app.use_global_filter("task-errors")
    return app


application = asgi(create_application)
