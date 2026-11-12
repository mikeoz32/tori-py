"""Executable tests for the persistent stream task activity tutorial."""

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingModule, http_client
from tori_py_persistent_streams_core import PublishOutcome, PublishReceipt

from .activity import TaskActivityPublisher, TaskCreatedV1
from .app import PIPELINE, application_module, create_application
from .models import CreateTaskBody, Task, TaskNotFound, TaskTitleInvalid
from .projection import ActivityEntry, ActivityLog
from .services import TaskService
from .state import TaskRepository


class RecordingPublisher:
    """A stand-in publisher that reports a fixed outcome."""

    def __init__(self, outcome: PublishOutcome = PublishOutcome.CONFIRMED) -> None:
        self.outcome = outcome
        self.published: list[TaskCreatedV1] = []

    async def task_created(
        self,
        payload: TaskCreatedV1,
        *,
        record_id: UUID | None = None,
    ) -> PublishReceipt:
        self.published.append(payload)
        return PublishReceipt(record_id or uuid4(), 0, self.outcome)


@pytest.mark.asyncio
async def test_task_service() -> None:
    publisher = RecordingPublisher()
    service = TaskService(TaskRepository(), publisher)

    assert service.all() == []

    first = await service.create(CreateTaskBody("  Write the tutorial  "))
    assert first == Task(1, "Write the tutorial")
    assert service.get(1) == first

    with pytest.raises(TaskTitleInvalid):
        await service.create(CreateTaskBody("   "))
    with pytest.raises(TaskTitleInvalid):
        await service.create(CreateTaskBody("x" * 121))

    second = await service.create(CreateTaskBody("Run the tests"))
    assert second == Task(2, "Run the tests")
    assert service.all() == [first, second]
    assert publisher.published == [
        TaskCreatedV1(1, "Write the tutorial"),
        TaskCreatedV1(2, "Run the tests"),
    ]

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
async def test_activity_follows_created_tasks() -> None:
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            health = await client.get("/streams/health")
            assert health.status_code == 200
            assert health.json()["ready"] is True
            assert health.json()["state"] == "running"

            for title in ("Plan", "Build", "Ship"):
                created = await client.post("/tasks", json={"title": title})
                assert created.status_code == 201

            # The projection is eventually consistent: wait for the handler.
            async with asyncio.timeout(2):
                while len((await client.get("/activity")).json()) < 3:
                    await asyncio.sleep(0.01)
            activity = (await client.get("/activity")).json()
    finally:
        await application.shutdown()

    assert [(entry["task_id"], entry["title"]) for entry in activity] == [
        (1, "Plan"),
        (2, "Build"),
        (3, "Ship"),
    ]
    assert {entry["partition"] for entry in activity} <= {0, 1}
    assert all(entry["offset"] >= 0 for entry in activity)


def test_activity_log_ignores_a_redelivered_record() -> None:
    log = ActivityLog()
    record_id = uuid4()
    entry = ActivityEntry(task_id=1, title="Plan", partition=0, offset=0)

    log.record(record_id, entry)
    log.record(record_id, entry)

    assert log.entries() == [entry]


@pytest.mark.asyncio
async def test_unconfirmed_activity_returns_503_after_saving() -> None:
    builder = TestingModule.create(application_module())
    builder.override_global(TaskActivityPublisher).use_value(
        RecordingPublisher(PublishOutcome.TIMED_OUT)
    )
    application = await builder.compile(adapter=StarletteAdapter(), pipeline=PIPELINE)
    try:
        async with http_client(application) as client:
            response = await client.post("/tasks", json={"title": "Unconfirmed"})
            _assert_problem(
                response,
                status_code=503,
                title="Service Unavailable",
                detail="The task was saved, but its activity record was not confirmed.",
                instance="/tasks",
            )
            listed = await client.get("/tasks")
            assert listed.json() == [{"id": 1, "title": "Unconfirmed"}]
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
