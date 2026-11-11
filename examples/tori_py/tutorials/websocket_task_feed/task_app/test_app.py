"""Executable tests for the WebSocket task feed tutorial."""

import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from tori_py.starlette import asgi
from tori_py.testing import http_client

from .app import create_application
from .feed import TaskFeed
from .models import CreateTaskBody, Task, TaskNotFound, TaskTitleInvalid
from .services import TaskService
from .state import TaskRepository


def test_task_service() -> None:
    service = TaskService(TaskRepository(), TaskFeed())

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


def test_feed_sends_a_snapshot_then_new_tasks() -> None:
    with TestClient(asgi(create_application)) as client:
        client.post("/tasks", json={"title": "Before connecting"})

        with client.websocket_connect("/tasks/live") as socket:
            assert socket.receive_json() == {
                "type": "snapshot",
                "tasks": [{"id": 1, "title": "Before connecting"}],
            }

            client.post("/tasks", json={"title": "  While connected  "})
            client.post("/tasks", json={"title": "Right after"})
            assert socket.receive_json() == {
                "type": "created",
                "task": {"id": 2, "title": "While connected"},
            }
            assert socket.receive_json() == {
                "type": "created",
                "task": {"id": 3, "title": "Right after"},
            }

        with client.websocket_connect(
            "/tasks/live",
            headers={"origin": "http://localhost:8000"},
        ) as socket:
            snapshot = socket.receive_json()
            assert [task["id"] for task in snapshot["tasks"]] == [1, 2, 3]


def test_feed_rejects_other_sites() -> None:
    with TestClient(asgi(create_application)) as client:
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect(
                "/tasks/live",
                headers={"origin": "https://attacker.example"},
            ):
                pass
        assert denied.value.code == 1008


@pytest.mark.asyncio
async def test_subscription_ends_with_its_context() -> None:
    feed = TaskFeed()
    async with feed.subscribe() as wakeup:
        assert feed.subscriber_count == 1
        feed.notify()
        assert wakeup.is_set()
    assert feed.subscriber_count == 0


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
