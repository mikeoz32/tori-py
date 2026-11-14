"""HTTP controller, ETags, and application-error translation."""

import re
from http import HTTPStatus
from typing import Annotated

import msgspec
from tori_py import (
    Body,
    Header,
    HttpResponse,
    Path,
    PipelineResult,
    controller,
    get,
    patch,
    post,
)
from tori_py.starlette import RequestContext
from tori_py.starlette.errors import problem_response
from tori_py_cqrs_core import CommandBus, QueryBus
from tori_py_cqrs_event_sourcing_core import (
    IndeterminateCommitError,
    OptimisticConcurrencyError,
)

from .messages import CreateTask, GetTask, ListTasks, RenameTask
from .models import (
    CreateTaskBody,
    InvalidIfMatch,
    RenameTaskBody,
    Task,
    TaskNotFound,
    TaskTitleInvalid,
    TaskVersionMismatch,
)
from .projection import VersionedTask

ETAG = re.compile(r'"([1-9][0-9]*)"')


@controller("/tasks")
class TaskController:
    def __init__(self, commands: CommandBus, queries: QueryBus) -> None:
        self._commands = commands
        self._queries = queries

    @post("")
    async def create(
        self,
        body: Annotated[CreateTaskBody, Body()],
    ) -> HttpResponse:
        created = await self._commands.execute(CreateTask(body))
        return task_response(created, status_code=201)

    @get("")
    async def list_tasks(self) -> list[Task]:
        return await self._queries.execute(ListTasks())

    @get("/{task_id}")
    async def get_one(
        self,
        task_id: Annotated[int, Path("task_id")],
    ) -> HttpResponse:
        return task_response(await self._queries.execute(GetTask(task_id)))

    @patch("/{task_id}")
    async def rename(
        self,
        task_id: Annotated[int, Path("task_id")],
        body: Annotated[RenameTaskBody, Body()],
        if_match: Annotated[str, Header("If-Match")] = "",
    ) -> HttpResponse:
        command = RenameTask(task_id, body, expected_version(if_match))
        return task_response(await self._commands.execute(command))


def task_response(result: VersionedTask, *, status_code: int = 200) -> HttpResponse:
    return HttpResponse(
        msgspec.json.encode(result.task),
        status_code=status_code,
        headers={
            "content-type": "application/json",
            "etag": f'"{result.version}"',
        },
    )


def expected_version(if_match: str) -> int | None:
    if not if_match:
        return None
    match = ETAG.fullmatch(if_match)
    if match is None:
        raise InvalidIfMatch
    return int(match.group(1))


class TaskErrorFilter:
    async def catch(
        self,
        error: Exception,
        context: RequestContext,
    ) -> PipelineResult:
        match error:
            case TaskTitleInvalid():
                status, detail = (
                    400,
                    "After trimming, the task title must contain 1-120 characters.",
                )
            case InvalidIfMatch():
                status, detail = 400, "If-Match must be an ETag returned by this API."
            case TaskNotFound():
                status, detail = 404, "Task was not found."
            case TaskVersionMismatch():
                status, detail = (
                    412,
                    "The task changed after you read it. Read it again first.",
                )
            case OptimisticConcurrencyError():
                status, detail = (
                    409,
                    "Another writer changed the task at the same time. Try again.",
                )
            case IndeterminateCommitError():
                status, detail = (
                    503,
                    "The event store did not confirm the write. "
                    "Read the task before you retry.",
                )
            case _:
                raise error
        return PipelineResult.from_response(
            problem_response(
                status,
                detail,
                request=context.request,
                title=HTTPStatus(status).phrase,
            )
        )
