"""HTTP controller and application-error translation."""

from __future__ import annotations

from typing import Annotated

from tori_py import (
    Body,
    Header,
    Path,
    PipelineResult,
    controller,
    get,
    post,
    status,
)
from tori_py.starlette import RequestContext
from tori_py.starlette.errors import problem_response
from tori_py_cqrs_core import CommandBus, QueryBus

from .models import (
    CreateTask,
    CreateTaskBody,
    GetTask,
    ListTasks,
    Task,
    TaskNotFound,
    TaskTitleInvalid,
)


@controller("/tasks")
class TaskController:
    def __init__(self, commands: CommandBus, queries: QueryBus) -> None:
        self._commands = commands
        self._queries = queries

    @post("")
    @status(202)
    async def create(
        self,
        body: Annotated[CreateTaskBody, Body()],
        actor: Annotated[str, Header("x-actor")],
    ) -> dict[str, object]:
        task = await self._commands.execute(CreateTask(body.title, actor))
        return {"task": task, "projection": "asynchronous-in-process"}

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
    async def catch(
        self,
        error: Exception,
        context: RequestContext,
    ) -> PipelineResult:
        if isinstance(error, TaskTitleInvalid):
            return PipelineResult.from_response(
                problem_response(
                    400,
                    "After trimming, the task title must contain 1-120 characters.",
                    request=context.request,
                )
            )
        if isinstance(error, TaskNotFound):
            return PipelineResult.from_response(
                problem_response(404, "Task was not found.", request=context.request)
            )
        raise error
