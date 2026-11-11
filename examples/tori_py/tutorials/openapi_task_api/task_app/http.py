"""HTTP controller, documentation metadata, and application-error translation."""

from typing import Annotated

from tori_py import (
    Body,
    HttpResponse,
    Path,
    PipelineResult,
    controller,
    delete,
    get,
    post,
    status,
    use_guard,
)
from tori_py.starlette import RequestContext
from tori_py.starlette.errors import problem_response
from tori_py_openapi import api_operation, api_response, api_security, api_tags

from .models import CreateTaskBody, Problem, Task, TaskNotFound, TaskTitleInvalid
from .services import TaskService

PROBLEM_JSON = "application/problem+json"

# Demonstration only. A real service validates a signed token from an identity
# provider instead of comparing one fixed value.
ADMIN_TOKEN = "tutorial-admin-token"


class AdminTokenGuard:
    async def can_activate(self, context: RequestContext) -> bool:
        return context.headers.get("authorization") == f"Bearer {ADMIN_TOKEN}"


@controller("/tasks")
@api_tags("tasks")
class TaskController:
    def __init__(self, tasks: TaskService) -> None:
        self._tasks = tasks

    @post("")
    @status(201)
    @api_operation(summary="Create a task", operation_id="tasks_create")
    @api_response(
        400,
        description="Invalid title or malformed body",
        model=Problem,
        media_type=PROBLEM_JSON,
    )
    async def create(
        self,
        body: Annotated[CreateTaskBody, Body()],
    ) -> Task:
        """Create a task with a trimmed title and the next ID.

        \f
        The service owns title normalization; this text is not published.
        """
        return self._tasks.create(body)

    @get("")
    @api_operation(summary="List tasks", operation_id="tasks_list")
    async def list_tasks(self) -> list[Task]:
        """Return every task in ID order."""
        return self._tasks.all()

    @get("/{task_id}")
    @api_operation(summary="Read a task", operation_id="tasks_get")
    @api_response(
        400,
        description="Task ID is not an integer",
        model=Problem,
        media_type=PROBLEM_JSON,
    )
    @api_response(
        404,
        description="Task was not found",
        model=Problem,
        media_type=PROBLEM_JSON,
    )
    async def get_one(
        self,
        task_id: Annotated[int, Path("task_id")],
    ) -> Task:
        return self._tasks.get(task_id)

    @delete("/{task_id}")
    @status(204)
    @use_guard(AdminTokenGuard)
    @api_security("admin")
    @api_operation(summary="Delete a task", operation_id="tasks_delete")
    @api_response(204, description="Task deleted")
    @api_response(
        400,
        description="Task ID is not an integer",
        model=Problem,
        media_type=PROBLEM_JSON,
    )
    @api_response(
        403,
        description="Missing or wrong admin token",
        model=Problem,
        media_type=PROBLEM_JSON,
    )
    @api_response(
        404,
        description="Task was not found",
        model=Problem,
        media_type=PROBLEM_JSON,
    )
    async def remove(
        self,
        task_id: Annotated[int, Path("task_id")],
    ) -> HttpResponse:
        self._tasks.delete(task_id)
        return HttpResponse(b"", status_code=204)


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
