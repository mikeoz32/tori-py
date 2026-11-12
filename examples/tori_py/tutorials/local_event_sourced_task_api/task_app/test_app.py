"""HTTP tests for the event-sourced Task API."""

import httpx
import pytest
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingApplication as ToriTestingApplication
from tori_py.testing import TestingModule, http_client
from tori_py_cqrs_event_sourcing import get_event_store_token
from tori_py_cqrs_event_sourcing_core import IndeterminateCommitError

from .app import PIPELINE, AppModule, TasksModule, create_application
from .app import event_sourcing_root as root
from .reconciliation import ReconciliationLog
from .state import EVENT_STORE_KEY
from .testing import CompetingWriterStore, FaultyStore, LostAcknowledgementStore


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
async def test_rename_checks_the_etag_the_client_read() -> None:
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            created = await client.post("/tasks", json={"title": "Plan"})
            assert created.headers["etag"] == '"1"'
            read = await client.get("/tasks/1")
            assert read.headers["etag"] == '"1"'

            renamed = await client.patch(
                "/tasks/1",
                json={"title": "  Plan the release  "},
                headers={"if-match": '"1"'},
            )
            assert renamed.status_code == 200
            assert renamed.headers["etag"] == '"2"'
            assert renamed.json() == {"id": 1, "title": "Plan the release"}

            stale = await client.patch(
                "/tasks/1",
                json={"title": "Lost update"},
                headers={"if-match": '"1"'},
            )
            _assert_problem(
                stale,
                status_code=412,
                title="Precondition Failed",
                detail="The task changed after you read it. Read it again first.",
                instance="/tasks/1",
            )

            unchanged = await client.patch(
                "/tasks/1",
                json={"title": "Plan the release"},
                headers={"if-match": '"2"'},
            )
            assert unchanged.headers["etag"] == '"2"'

            unconditional = await client.patch("/tasks/1", json={"title": "Ship"})
            assert unconditional.headers["etag"] == '"3"'
            assert (await client.get("/tasks")).json() == [{"id": 1, "title": "Ship"}]

            weak = await client.patch(
                "/tasks/1",
                json={"title": "Ship"},
                headers={"if-match": 'W/"3"'},
            )
            _assert_problem(
                weak,
                status_code=400,
                title="Bad Request",
                detail="If-Match must be an ETag returned by this API.",
                instance="/tasks/1",
            )

            invalid = await client.patch("/tasks/1", json={"title": " "})
            assert invalid.status_code == 400
            missing = await client.patch("/tasks/999", json={"title": "Ship"})
            assert missing.status_code == 404
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_a_competing_writer_turns_the_rename_into_409() -> None:
    store = CompetingWriterStore()
    application = await _compile_with(store)
    try:
        async with http_client(application) as client:
            await client.post("/tasks", json={"title": "Plan"})

            store.armed = True
            conflict = await client.patch(
                "/tasks/1",
                json={"title": "Renamed"},
                headers={"if-match": '"1"'},
            )
            _assert_problem(
                conflict,
                status_code=409,
                title="Conflict",
                detail="Another writer changed the task at the same time. Try again.",
                instance="/tasks/1",
            )

            # The other writer's change is stored; retry from what it wrote.
            current = await client.get("/tasks/1")
            assert current.headers["etag"] == '"2"'
            retried = await client.patch(
                "/tasks/1",
                json={"title": "Renamed again"},
                headers={"if-match": current.headers["etag"]},
            )
            assert retried.status_code == 200
            assert retried.headers["etag"] == '"3"'
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_a_lost_acknowledgement_is_503_not_a_rollback() -> None:
    store = LostAcknowledgementStore()
    application = await _compile_with(store)
    try:
        reconciliation = await application.resolve(
            ReconciliationLog, module=TasksModule
        )
        assert isinstance(reconciliation, ReconciliationLog)
        async with http_client(application) as client:
            store.armed = True
            unknown = await client.post("/tasks", json={"title": "Unconfirmed"})
            _assert_problem(
                unknown,
                status_code=503,
                title="Service Unavailable",
                detail=(
                    "The event store did not confirm the write. "
                    "Read the task before you retry."
                ),
                instance="/tasks",
            )
            assert [entry.task_id for entry in reconciliation.entries] == [1]
            assert isinstance(reconciliation.entries[0].cause, IndeterminateCommitError)

            # The write did happen, so a blind retry would create a duplicate.
            stored = await client.get("/tasks/1")
            assert stored.json() == {"id": 1, "title": "Unconfirmed"}
    finally:
        await application.close()


async def _compile_with(store: FaultyStore) -> ToriTestingApplication:
    builder = TestingModule.create(AppModule)
    builder.override_provider(
        get_event_store_token(key=EVENT_STORE_KEY),
        module=root,
    ).use_value(store)
    return await builder.compile(adapter=StarletteAdapter(), pipeline=PIPELINE)


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
