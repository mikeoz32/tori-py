import json

import pytest
from nestpy import StarletteOptions
from nestpy.settings import BootstrapContext, use_bootstrap_context
from nestpy.testing import TestingModule

from examples.nestpy.reference_apps.task_api.app import (
    AppModule,
    InfrastructureModule,
    TaskRepository,
    create_application,
)


@pytest.mark.asyncio
async def test_task_api_reference_application(
    call_http,
    message_body,
    message_headers,
) -> None:
    application = await create_application()
    await application.start()
    try:
        denied = await call_http(
            application.http_app,
            method="POST",
            path="/tasks",
            body=b'{"title":"blocked"}',
            headers=[(b"content-type", b"application/json")],
        )
        assert denied[0]["status"] == 403

        created = await call_http(
            application.http_app,
            method="POST",
            path="/tasks",
            body=b'{"title":"  Document Task API  "}',
            headers=[
                (b"content-type", b"application/json"),
                (b"x-task-write", b"allow"),
                (b"x-request-id", b"task-api-test"),
            ],
        )
        assert created[0]["status"] == 201
        assert json.loads(message_body(created[1])) == {
            "task": {"id": 1, "title": "Document Task API"},
            "marker": "request-scope",
            "request_id": "task-api-test",
        }

        listed = await call_http(application.http_app, path="/tasks")
        assert json.loads(message_body(listed[1])) == [
            {"id": 1, "title": "Document Task API"}
        ]

        found = await call_http(application.http_app, path="/tasks/1")
        assert json.loads(message_body(found[1])) == {
            "id": 1,
            "title": "Document Task API",
        }

        missing = await call_http(application.http_app, path="/tasks/999")
        assert missing[0]["status"] == 404
        assert dict(message_headers(missing[0]))[b"content-type"] == (
            b"application/problem+json"
        )
        assert json.loads(message_body(missing[1]))["detail"] == "Task was not found."

        invalid = await call_http(
            application.http_app,
            method="POST",
            path="/tasks",
            body=b'{"title": 3}',
            headers=[
                (b"content-type", b"application/json"),
                (b"x-task-write", b"allow"),
            ],
        )
        assert invalid[0]["status"] == 400
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_task_api_reference_uses_bootstrap_settings_override(call_http) -> None:
    with use_bootstrap_context(BootstrapContext((("max_title_length", "4"),))):
        application = await create_application()
    await application.start()
    try:
        response = await call_http(
            application.http_app,
            method="POST",
            path="/tasks",
            body=b'{"title":"longer"}',
            headers=[
                (b"content-type", b"application/json"),
                (b"x-task-write", b"allow"),
            ],
        )
        assert response[0]["status"] == 400
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_task_api_reference_supports_repository_override(
    call_http,
    message_body,
) -> None:
    repository = TaskRepository()
    repository.create("From test override")
    builder = TestingModule.create(AppModule)
    builder.override_provider(TaskRepository, module=InfrastructureModule).use_value(
        repository
    )
    application = await builder.compile(
        http=StarletteOptions(pipes=("validation",), filters=("task-errors",))
    )
    try:
        response = await call_http(application.asgi, path="/tasks")
        assert json.loads(message_body(response[1])) == [
            {"id": 1, "title": "From test override"}
        ]
    finally:
        await application.close()
