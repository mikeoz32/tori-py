import pytest
from tori_py import PipelineOptions
from tori_py.settings import BootstrapContext, use_bootstrap_context
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingModule, http_client

from examples.tori_py.reference_apps.task_api.app import (
    AppModule,
    InfrastructureModule,
    TaskRepository,
    create_application,
)


@pytest.mark.asyncio
async def test_task_api_reference_application() -> None:
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            denied = await client.post("/tasks", json={"title": "blocked"})
            assert denied.status_code == 403

            created = await client.post(
                "/tasks",
                json={"title": "  Document Task API  "},
                headers={
                    "x-task-write": "allow",
                    "x-request-id": "task-api-test",
                },
            )
            assert created.status_code == 201
            assert created.json() == {
                "task": {"id": 1, "title": "Document Task API"},
                "marker": "request-scope",
                "request_id": "task-api-test",
            }

            listed = await client.get("/tasks")
            assert listed.json() == [{"id": 1, "title": "Document Task API"}]

            found = await client.get("/tasks/1")
            assert found.json() == {"id": 1, "title": "Document Task API"}

            missing = await client.get("/tasks/999")
            assert missing.status_code == 404
            assert missing.headers["content-type"] == "application/problem+json"
            assert missing.json()["detail"] == "Task was not found."

            invalid = await client.post(
                "/tasks",
                json={"title": 3},
                headers={"x-task-write": "allow"},
            )
            assert invalid.status_code == 400
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_task_api_reference_uses_bootstrap_settings_override() -> None:
    with use_bootstrap_context(BootstrapContext((("max_title_length", "4"),))):
        application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            response = await client.post(
                "/tasks",
                json={"title": "longer"},
                headers={"x-task-write": "allow"},
            )
            assert response.status_code == 400
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_task_api_reference_supports_repository_override() -> None:
    repository = TaskRepository()
    repository.create("From test override")
    builder = TestingModule.create(AppModule)
    builder.override_provider(TaskRepository, module=InfrastructureModule).use_value(
        repository
    )
    application = await builder.compile(
        pipeline=PipelineOptions(
            pipes=("validation",),
            filters=("task-errors",),
        ),
        adapter=StarletteAdapter(),
    )
    try:
        async with application.http_client() as client:
            response = await client.get("/tasks")
            assert response.json() == [{"id": 1, "title": "From test override"}]
    finally:
        await application.close()
