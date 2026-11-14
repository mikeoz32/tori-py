"""Executable tests for the protected Task API."""

import httpx
import pytest
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingModule, http_client

from .app import PIPELINE, AppModule, AuthModule, create_application
from .auth import Principal, TokenVerifier
from .models import CreateTaskBody, Task, TaskNotFound, TaskTitleInvalid
from .services import TaskService
from .state import TaskRepository

ALICE = {"authorization": "Bearer alice-token"}
BOB = {"authorization": "Bearer bob-token"}


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
async def test_http_contract_holds_for_a_signed_in_caller() -> None:
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            empty = await client.get("/tasks")
            assert empty.status_code == 200
            assert empty.json() == []

            for title in ("   ", "x" * 121):
                invalid_title = await client.post(
                    "/tasks", json={"title": title}, headers=BOB
                )
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
                headers={"content-type": "application/json", **BOB},
            )
            _assert_problem(
                malformed,
                status_code=400,
                title="Bad Request",
                detail="Request body contains malformed JSON.",
                instance="/tasks",
            )

            missing = await client.post("/tasks", json={}, headers=BOB)
            _assert_validation_problem(
                missing,
                parameter="body",
                source="body",
                message="Object missing required field `title`",
            )

            unknown = await client.post(
                "/tasks",
                json={"title": "Hidden metadata", "unexpected": True},
                headers=BOB,
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
                headers=BOB,
            )
            assert created.status_code == 201
            assert created.json() == {"id": 1, "title": "Ship Part 1"}

            second = await client.post(
                "/tasks", json={"title": "Verify order"}, headers=BOB
            )
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
async def test_writes_need_a_valid_bearer_token() -> None:
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            anonymous = await client.post("/tasks", json={"title": "Plan"})
            _assert_problem(
                anonymous,
                status_code=401,
                title="Unauthorized",
                detail="Send a bearer token to do this.",
                instance="/tasks",
            )
            assert anonymous.headers["www-authenticate"] == "Bearer"

            for authorization in ("Bearer wrong-token", "Basic Ym9iOg==", "Bearer"):
                rejected = await client.post(
                    "/tasks",
                    json={"title": "Plan"},
                    headers={"authorization": authorization},
                )
                _assert_problem(
                    rejected,
                    status_code=401,
                    title="Unauthorized",
                    detail="The bearer token is not valid.",
                    instance="/tasks",
                )
                assert rejected.headers["www-authenticate"] == (
                    'Bearer error="invalid_token"'
                )

            # A token is optional on reads, but a wrong one is still rejected.
            assert (await client.get("/tasks")).status_code == 200
            wrong_read = await client.get(
                "/tasks", headers={"authorization": "Bearer wrong-token"}
            )
            assert wrong_read.status_code == 401
            assert (await client.get("/tasks")).json() == []
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_only_admins_read_the_audit_log() -> None:
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            await client.post("/tasks", json={"title": "Plan"}, headers=BOB)
            await client.post("/tasks", json={"title": " "}, headers=BOB)
            await client.post("/tasks", json={"title": "Denied"})

            anonymous = await client.get("/audit")
            assert anonymous.status_code == 401
            _assert_problem(
                await client.get("/audit", headers=BOB),
                status_code=403,
                title="Forbidden",
                detail="Forbidden.",
                instance="/audit",
            )

            audit = await client.get("/audit", headers=ALICE)
            assert audit.status_code == 200
            assert audit.json() == [
                {"actor": "bob", "route": "POST /tasks", "outcome": "succeeded"},
                {"actor": "bob", "route": "POST /tasks", "outcome": "failed"},
            ]
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_maintenance_mode_answers_before_the_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TASK_API_MAINTENANCE", "on")
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            for response in (
                await client.get("/tasks"),
                await client.post(
                    "/tasks",
                    json={"title": "Plan"},
                    headers={"authorization": "Bearer wrong-token"},
                ),
            ):
                _assert_problem(
                    response,
                    status_code=503,
                    title="Service Unavailable",
                    detail="The Task API is down for maintenance. Try again later.",
                    instance="/tasks",
                )
                assert response.headers["retry-after"] == "60"
    finally:
        await application.shutdown()


class OneTokenVerifier:
    """A stand-in identity source for tests."""

    async def verify(self, token: str) -> Principal | None:
        if token == "test-token":
            return Principal("tester", frozenset({"admin"}))
        return None


@pytest.mark.asyncio
async def test_a_test_replaces_the_token_verifier() -> None:
    builder = TestingModule.create(AppModule)
    builder.override_provider(TokenVerifier, module=AuthModule).use_value(
        OneTokenVerifier()
    )
    application = await builder.compile(adapter=StarletteAdapter(), pipeline=PIPELINE)
    try:
        async with http_client(application) as client:
            tester = {"authorization": "Bearer test-token"}
            created = await client.post(
                "/tasks", json={"title": "Plan"}, headers=tester
            )
            assert created.status_code == 201
            assert (await client.get("/audit", headers=tester)).json() == [
                {"actor": "tester", "route": "POST /tasks", "outcome": "succeeded"}
            ]
            assert (await client.get("/audit", headers=ALICE)).status_code == 401
    finally:
        await application.close()


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
