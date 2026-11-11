"""Executable tests for the OpenAPI Task API tutorial."""

import httpx
import msgspec
import pytest
from tori_py.testing import http_client

from .app import create_application
from .http import ADMIN_TOKEN
from .models import CreateTaskBody, Problem, Task, TaskNotFound, TaskTitleInvalid
from .services import TaskService
from .state import TaskRepository

ADMIN = {"authorization": f"Bearer {ADMIN_TOKEN}"}
PROBLEM = {
    "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
}


def test_task_service() -> None:
    service = TaskService(TaskRepository())

    assert service.all() == []

    first = service.create(CreateTaskBody("  Write the tutorial  "))
    assert first == Task(1, "Write the tutorial")
    assert service.get(1) == first

    with pytest.raises(TaskTitleInvalid):
        service.create(CreateTaskBody("   "))
    with pytest.raises(TaskTitleInvalid):
        service.create(CreateTaskBody("x" * 121))

    second = service.create(CreateTaskBody("Run the tests"))
    assert second == Task(2, "Run the tests")
    assert service.all() == [first, second]

    with pytest.raises(TaskNotFound):
        service.get(999)


@pytest.mark.asyncio
async def test_http_contract_has_no_architecture_metadata() -> None:
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            empty = await client.get("/tasks")
            assert empty.status_code == 200
            assert empty.json() == []

            for title in ("   ", "x" * 121):
                invalid_title = await client.post("/tasks", json={"title": title})
                _assert_problem(
                    invalid_title,
                    status_code=400,
                    title="Bad Request",
                    detail=(
                        "After trimming, the task title must contain 1-120 characters."
                    ),
                    instance="/tasks",
                )

            malformed = await client.post(
                "/tasks",
                content=b'{"title":',
                headers={"content-type": "application/json"},
            )
            _assert_problem(
                malformed,
                status_code=400,
                title="Bad Request",
                detail="Request body contains malformed JSON.",
                instance="/tasks",
            )

            missing = await client.post("/tasks", json={})
            _assert_validation_problem(
                missing,
                parameter="body",
                source="body",
                message="Object missing required field `title`",
            )

            unknown = await client.post(
                "/tasks",
                json={"title": "Hidden metadata", "unexpected": True},
            )
            _assert_validation_problem(
                unknown,
                parameter="body",
                source="body",
                message="Object contains unknown field `unexpected`",
            )

            invalid_path = await client.get("/tasks/not-an-integer")
            _assert_validation_problem(
                invalid_path,
                parameter="task_id",
                source="path",
                message=("invalid literal for int() with base 10: 'not-an-integer'"),
                instance="/tasks/not-an-integer",
            )

            created = await client.post(
                "/tasks",
                json={"title": "  Ship Part 1  "},
            )
            assert created.status_code == 201
            assert created.json() == {"id": 1, "title": "Ship Part 1"}

            second = await client.post("/tasks", json={"title": "Verify order"})
            assert second.status_code == 201
            assert second.json() == {"id": 2, "title": "Verify order"}

            listed = await client.get("/tasks")
            assert listed.status_code == 200
            assert listed.json() == [created.json(), second.json()]

            found = await client.get("/tasks/1")
            assert found.status_code == 200
            assert found.json() == created.json()

            not_found = await client.get("/tasks/999")
            _assert_problem(
                not_found,
                status_code=404,
                title="Not Found",
                detail="Task was not found.",
                instance="/tasks/999",
            )
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_openapi_document_describes_the_api() -> None:
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            document = (await client.get("/openapi.json")).json()
            swagger = await client.get("/docs")
    finally:
        await application.shutdown()

    assert document["openapi"] == "3.1.0"
    assert document["info"] == {
        "title": "Task API",
        "version": "1.0.0",
        "description": "Create, read, and delete tasks.",
    }
    operations = {
        (path, method): operation
        for path, item in document["paths"].items()
        for method, operation in item.items()
    }
    assert {key: operation["operationId"] for key, operation in operations.items()} == {
        ("/tasks", "post"): "tasks_create",
        ("/tasks", "get"): "tasks_list",
        ("/tasks/{task_id}", "get"): "tasks_get",
        ("/tasks/{task_id}", "delete"): "tasks_delete",
    }
    assert all(operation["tags"] == ["tasks"] for operation in operations.values())
    assert {
        key: sorted(operation["responses"]) for key, operation in operations.items()
    } == {
        ("/tasks", "post"): ["201", "400"],
        ("/tasks", "get"): ["200"],
        ("/tasks/{task_id}", "get"): ["200", "400", "404"],
        ("/tasks/{task_id}", "delete"): ["204", "400", "403", "404"],
    }

    create = operations[("/tasks", "post")]
    assert (
        create["description"] == "Create a task with a trimmed title and the next ID."
    )
    assert create["responses"]["400"]["content"] == PROBLEM

    remove = operations[("/tasks/{task_id}", "delete")]
    assert remove["responses"]["204"] == {"description": "Task deleted"}
    assert remove["responses"]["403"]["content"] == PROBLEM
    assert remove["security"] == [{"admin": []}]
    assert all(
        "security" not in operation
        for key, operation in operations.items()
        if key != ("/tasks/{task_id}", "delete")
    )
    assert document["components"]["securitySchemes"] == {
        "admin": {
            "type": "http",
            "scheme": "bearer",
            "description": "Administrator token",
        }
    }

    assert swagger.status_code == 200
    assert "SwaggerUIBundle" in swagger.text


@pytest.mark.asyncio
async def test_delete_requires_the_admin_token() -> None:
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            await client.post("/tasks", json={"title": "Remove me"})

            for headers in ({}, {"authorization": "Bearer wrong"}):
                denied = await client.delete("/tasks/1", headers=headers)
                _assert_problem(
                    denied,
                    status_code=403,
                    title="Forbidden",
                    detail="Forbidden.",
                    instance="/tasks/1",
                )

            deleted = await client.delete("/tasks/1", headers=ADMIN)
            assert deleted.status_code == 204
            assert deleted.content == b""
            assert (await client.get("/tasks")).json() == []

            missing = await client.delete("/tasks/1", headers=ADMIN)
            _assert_problem(
                missing,
                status_code=404,
                title="Not Found",
                detail="Task was not found.",
                instance="/tasks/1",
            )
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_error_responses_match_the_documented_problem_model() -> None:
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            responses = [
                await client.post("/tasks", json={"title": "   "}),
                await client.post("/tasks", json={}),
                await client.get("/tasks/not-an-integer"),
                await client.get("/tasks/999"),
                await client.delete("/tasks/999"),
            ]
    finally:
        await application.shutdown()

    problems = [msgspec.json.decode(r.content, type=Problem) for r in responses]
    assert [problem.status for problem in problems] == [400, 400, 400, 404, 403]
    assert problems[1].errors is not msgspec.UNSET


def _assert_validation_problem(
    response: httpx.Response,
    *,
    parameter: str,
    source: str,
    message: str,
    instance: str = "/tasks",
) -> None:
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body == {
        "type": "about:blank",
        "title": "Bad Request",
        "status": 400,
        "detail": "Validation failed.",
        "instance": instance,
        "errors": {
            "parameter": parameter,
            "source": source,
            "message": message,
        },
    }


def _assert_problem(
    response: httpx.Response,
    *,
    status_code: int,
    title: str,
    detail: str,
    instance: str,
) -> None:
    assert response.status_code == status_code
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": instance,
    }
