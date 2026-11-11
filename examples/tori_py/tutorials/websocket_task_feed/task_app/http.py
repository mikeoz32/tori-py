"""HTTP controller and application-error translation."""

from typing import Annotated

from tori_py import Body, Path, PipelineResult, controller, get, post, status
from tori_py.starlette import RequestContext
from tori_py.starlette.errors import problem_response

from .models import CreateTaskBody, Task, TaskNotFound, TaskTitleInvalid
from .services import TaskService


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
        return self._tasks.create(body)

    @get("")
    async def list_tasks(self) -> list[Task]:
        return self._tasks.all()

    @get("/{task_id}")
    async def get_one(
        self,
        task_id: Annotated[int, Path("task_id")],
    ) -> Task:
        return self._tasks.get(task_id)


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
