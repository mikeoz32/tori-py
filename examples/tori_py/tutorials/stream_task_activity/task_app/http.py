"""HTTP controllers and application-error translation."""

from typing import Annotated

import msgspec
from tori_py import (
    Body,
    HttpResponse,
    Path,
    PipelineResult,
    controller,
    get,
    post,
    status,
)
from tori_py.starlette import RequestContext
from tori_py.starlette.errors import problem_response
from tori_py_persistent_streams import StreamRuntime

from .models import CreateTaskBody, Task, TaskNotFound, TaskTitleInvalid
from .projection import ActivityEntry, ActivityLog
from .services import ActivityNotRecorded, TaskService


@controller("/tasks")
class TaskController:
    def __init__(self, tasks: TaskService) -> None:
        self._tasks = tasks

    @post("")
    @status(201)
    async def create(
        self,
        body: Annotated[CreateTaskBody, Body()],
    ) -> Task:
        return await self._tasks.create(body)

    @get("")
    async def list_tasks(self) -> list[Task]:
        return self._tasks.all()

    @get("/{task_id}")
    async def get_one(
        self,
        task_id: Annotated[int, Path("task_id")],
    ) -> Task:
        return self._tasks.get(task_id)


class PartitionHealth(msgspec.Struct, frozen=True):
    stream: str
    consumer_group: str
    partition: int
    state: str
    offset: int | None
    diagnostic_code: str | None


class StreamHealth(msgspec.Struct, frozen=True):
    ready: bool
    state: str
    partitions: list[PartitionHealth]


@controller()
class ActivityController:
    def __init__(self, log: ActivityLog, runtime: StreamRuntime) -> None:
        self._log = log
        self._runtime = runtime

    @get("/activity")
    async def activity(self) -> list[ActivityEntry]:
        return self._log.entries()

    @get("/streams/health")
    async def health(self) -> HttpResponse:
        health = StreamHealth(
            ready=self._runtime.ready,
            state=self._runtime.state.value,
            partitions=[
                PartitionHealth(
                    stream=status.stream,
                    consumer_group=status.consumer_group,
                    partition=status.partition,
                    state=status.state,
                    offset=status.offset,
                    diagnostic_code=status.diagnostic_code,
                )
                for status in self._runtime.statuses
            ],
        )
        return HttpResponse(
            msgspec.json.encode(health),
            status_code=200 if health.ready else 503,
            headers={"Content-Type": "application/json"},
        )


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
        if isinstance(error, ActivityNotRecorded):
            return PipelineResult.from_response(
                problem_response(
                    503,
                    "The task was saved, but its activity record was not confirmed.",
                    request=context.request,
                )
            )
        raise error
