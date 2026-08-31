"""Executable tests shown in the CQRS application tutorial."""

import pytest
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingModule
from tori_py_cqrs_core import CommandBus, EventBus, QueryBus

from .app import AppModule, TasksModule, pipeline_options
from .models import CreateTask, GetTask, ListTasks
from .state import TaskAuditLog, TaskProjection


@pytest.mark.asyncio
async def test_commands_events_and_queries() -> None:
    application = await TestingModule.create(AppModule).compile(
        adapter=StarletteAdapter(),
        pipeline=pipeline_options,
    )
    try:
        commands = await application.resolve(CommandBus)
        queries = await application.resolve(QueryBus)
        events = await application.resolve(EventBus)
        projection = await application.resolve(TaskProjection, module=TasksModule)
        audit = await application.resolve(TaskAuditLog, module=TasksModule)
        assert isinstance(commands, CommandBus)
        assert isinstance(queries, QueryBus)
        assert isinstance(events, EventBus)
        assert isinstance(projection, TaskProjection)
        assert isinstance(audit, TaskAuditLog)

        task = await commands.execute(CreateTask("Write the tutorial", "alice"))
        await projection.wait_for_count(1, timeout=1)
        await audit.wait_for_count(1, timeout=1)
        await events.drain(timeout=1)

        assert await queries.execute(GetTask(task.id)) == task
        assert await queries.execute(ListTasks()) == [task]
        assert audit.entries[0].actor == "alice"
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_http_api() -> None:
    application = await TestingModule.create(AppModule).compile(
        adapter=StarletteAdapter(),
        pipeline=pipeline_options,
    )
    try:
        projection = await application.resolve(TaskProjection, module=TasksModule)
        audit = await application.resolve(TaskAuditLog, module=TasksModule)
        assert isinstance(projection, TaskProjection)
        assert isinstance(audit, TaskAuditLog)

        async with application.http_client() as client:
            invalid = await client.post(
                "/tasks",
                json={"title": "   "},
                headers={"x-actor": "alice"},
            )
            assert invalid.status_code == 400
            assert invalid.headers["content-type"].startswith(
                "application/problem+json"
            )
            assert invalid.json()["detail"] == (
                "After trimming, the task title must contain 1-120 characters."
            )

            created = await client.post(
                "/tasks",
                json={"title": "  Ship the tutorial  "},
                headers={"x-actor": "alice"},
            )
            assert created.status_code == 202
            assert created.json() == {
                "task": {
                    "id": 1,
                    "title": "Ship the tutorial",
                    "created_by": "alice",
                },
                "projection": "asynchronous-in-process",
            }
            task = created.json()["task"]

            await projection.wait_for_count(1, timeout=1)
            await audit.wait_for_count(1, timeout=1)

            listed = await client.get("/tasks")
            assert listed.status_code == 200
            assert listed.json() == [task]

            found = await client.get("/tasks/1")
            assert found.status_code == 200
            assert found.json() == task

            missing = await client.get("/tasks/999")
            assert missing.status_code == 404
    finally:
        await application.close()
