"""Executable verification for the advanced Nestpy CQRS example."""

import pytest
from cqrs_core import CommandBus, EventBus, QueryBus
from nestpy.starlette import StarletteAdapter
from nestpy.testing import TestingModule

from examples.nestpy.cqrs.advanced.app import (
    AppModule,
    AuditLog,
    CreateTask,
    GetTask,
    ListTasks,
    ScopeMetrics,
    TaskProjection,
    TasksModule,
    pipeline_options,
)


@pytest.mark.asyncio
async def test_discovered_handlers_use_scopes_events_and_projection() -> None:
    application = await TestingModule.create(AppModule).compile(
        adapter=StarletteAdapter(),
        pipeline=pipeline_options,
    )
    try:
        commands = await application.resolve(CommandBus)
        queries = await application.resolve(QueryBus)
        events = await application.resolve(EventBus)
        metrics = await application.resolve(ScopeMetrics, module=TasksModule)
        audit = await application.resolve(AuditLog, module=TasksModule)
        projection = await application.resolve(TaskProjection, module=TasksModule)
        assert isinstance(commands, CommandBus)
        assert isinstance(queries, QueryBus)
        assert isinstance(events, EventBus)
        assert isinstance(metrics, ScopeMetrics)
        assert isinstance(audit, AuditLog)
        assert isinstance(projection, TaskProjection)

        first = await commands.execute(CreateTask("First task", "alice"))
        second = await commands.execute(CreateTask("Second task", "bob"))
        await projection.wait_for_count(2, timeout=1)
        await audit.wait_for_count(2, timeout=1)
        await events.drain(timeout=1)

        assert await queries.execute(GetTask(first.id)) == first
        assert await queries.execute(ListTasks()) == [first, second]
        assert sorted((entry.task_id, entry.actor) for entry in audit.entries) == [
            (first.id, "alice"),
            (second.id, "bob"),
        ]
        assert metrics.command_scope_entries == 2
        assert metrics.command_scope_exits == 2
        assert metrics.command_handler_constructions == 2
        assert metrics.command_handler_sequences == [1, 2]
        assert metrics.projection_handler_constructions == 2
        assert metrics.query_handler_constructions == 2
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_http_adapter_dispatches_commands_and_queries() -> None:
    application = await TestingModule.create(AppModule).compile(
        adapter=StarletteAdapter(),
        pipeline=pipeline_options,
    )
    try:
        metrics = await application.resolve(ScopeMetrics, module=TasksModule)
        projection = await application.resolve(TaskProjection, module=TasksModule)
        audit = await application.resolve(AuditLog, module=TasksModule)
        assert isinstance(metrics, ScopeMetrics)
        assert isinstance(projection, TaskProjection)
        assert isinstance(audit, AuditLog)

        async with application.http_client() as client:
            malformed = await client.post(
                "/tasks",
                json={"title": 7},
                headers={"x-actor": "alice"},
            )
            assert malformed.status_code == 400

            invalid = await client.post(
                "/tasks",
                json={"title": "   "},
                headers={"x-actor": "alice"},
            )
            assert invalid.status_code == 400
            assert invalid.json()["status"] == 400
            assert metrics.command_scope_entries == 1
            assert metrics.command_scope_exits == 1

            response = await client.post(
                "/tasks",
                json={"title": "HTTP task"},
                headers={"x-actor": "alice"},
            )
            assert response.status_code == 202
            created = response.json()
            created_task = created["task"]
            assert created_task["title"] == "HTTP task"
            assert created["projection"] == "asynchronous-in-process"

            events = await application.resolve(EventBus)
            assert isinstance(events, EventBus)
            await projection.wait_for_count(1, timeout=1)
            await audit.wait_for_count(1, timeout=1)
            await events.drain(timeout=1)

            listed = await client.get("/tasks")
            assert listed.status_code == 200
            assert listed.json() == [created_task]

            missing = await client.get("/tasks/999")
            assert missing.status_code == 404
        assert metrics.command_scope_entries == 2
        assert metrics.command_scope_exits == 2
    finally:
        await application.close()
