"""Executable tests for the Live Task Board tutorial."""

import httpx
import pytest
from starlette.datastructures import QueryParams
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingModule, http_client
from tori_py_cqrs_core import CommandBus, EventBus, QueryBus
from tori_py_liveview import MountContext
from tori_py_liveview_ui import STYLESHEET_PATH

from .app import AppModule, TasksModule, create_application
from .feed import TaskBoardFeed
from .live import TITLE_ERROR, TaskBoardLive
from .messages import CreateTask, GetTask, ListTasks
from .models import CreateTaskBody, Task, TaskNotFound, TaskTitleInvalid
from .observers import TaskAuditLog, TaskMetrics


@pytest.mark.asyncio
async def test_commands_have_immediate_repository_backed_queries() -> None:
    application = await TestingModule.create(AppModule).compile(
        adapter=StarletteAdapter()
    )
    try:
        commands = await application.resolve(CommandBus)
        queries = await application.resolve(QueryBus)
        assert isinstance(commands, CommandBus)
        assert isinstance(queries, QueryBus)

        assert await queries.execute(ListTasks()) == []

        task = await commands.execute(
            CreateTask(CreateTaskBody("  Write the tutorial  "))
        )
        assert task == Task(1, "Write the tutorial")
        assert await queries.execute(GetTask(task.id)) == task
        assert await queries.execute(ListTasks()) == [task]

        with pytest.raises(TaskTitleInvalid):
            await commands.execute(CreateTask(CreateTaskBody("   ")))
        with pytest.raises(TaskNotFound):
            await queries.execute(GetTask(999))
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_task_created_fans_out_to_audit_and_metrics() -> None:
    application = await TestingModule.create(AppModule).compile(
        adapter=StarletteAdapter()
    )
    try:
        commands = await application.resolve(CommandBus)
        events = await application.resolve(EventBus)
        audit = await application.resolve(TaskAuditLog, module=TasksModule)
        metrics = await application.resolve(TaskMetrics, module=TasksModule)
        assert isinstance(commands, CommandBus)
        assert isinstance(events, EventBus)
        assert isinstance(audit, TaskAuditLog)
        assert isinstance(metrics, TaskMetrics)

        task = await commands.execute(CreateTask(CreateTaskBody("Observe events")))
        await audit.wait_for_count(1, timeout=1)
        await metrics.wait_for_created(1, timeout=1)
        await events.drain(timeout=1)

        assert audit.entries == [task]
        assert metrics.created == 1
    finally:
        await application.close()


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
async def test_board_renders_existing_tasks_over_http() -> None:
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            empty = await client.get("/board")
            assert "No tasks yet." in empty.text

            await client.post("/tasks", json={"title": "Write <docs>"})
            await client.post("/tasks", json={"title": "Review docs"})
            board = await client.get("/board")
    finally:
        await application.shutdown()

    assert board.status_code == 200
    assert board.headers["cache-control"] == "no-store"
    assert '<title data-default="">Task board (2)</title>' in board.text
    assert STYLESHEET_PATH in board.text
    assert "No tasks yet." not in board.text
    first = board.text.index('<li id="task-2">')
    second = board.text.index('<li id="task-1">')
    assert first < second
    assert "Write &lt;docs&gt;" in board.text


@pytest.mark.asyncio
async def test_board_validates_creates_and_catches_up() -> None:
    application = await TestingModule.create(AppModule).compile(
        adapter=StarletteAdapter()
    )
    try:
        commands = await application.resolve(CommandBus)
        queries = await application.resolve(QueryBus)
        feed = await application.resolve(TaskBoardFeed, module=TasksModule)
        assert isinstance(commands, CommandBus)
        assert isinstance(queries, QueryBus)
        assert isinstance(feed, TaskBoardFeed)

        page = TaskBoardLive(commands, queries, feed)
        await page.mount(_mount_context())
        assert page.task_count == 0

        await page.handle_event("validate", {"task": {"title": "   "}})
        assert page.error == TITLE_ERROR
        await page.handle_event("create", {"task": {"title": "x" * 121}})
        assert page.error == TITLE_ERROR
        assert page.task_count == 0

        await page.handle_event("create", {"task": {"title": "  Ship the board  "}})
        assert page.error is None
        assert page.draft == ""
        assert page.task_count == 1

        await commands.execute(CreateTask(CreateTaskBody("Created elsewhere")))
        await page.handle_info("tasks_changed", None)
        assert page.task_count == 2
        assert page.last_task_id == 2

        items = page.stream_contents("tasks").value
        assert items.index("Created elsewhere") < items.index("Ship the board")
        assert page.title() == "Task board (2)"
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_task_created_wakes_subscribed_boards() -> None:
    application = await TestingModule.create(AppModule).compile(
        adapter=StarletteAdapter()
    )
    try:
        commands = await application.resolve(CommandBus)
        events = await application.resolve(EventBus)
        feed = await application.resolve(TaskBoardFeed, module=TasksModule)
        assert isinstance(commands, CommandBus)
        assert isinstance(events, EventBus)
        assert isinstance(feed, TaskBoardFeed)

        board = _RecordingBoard()
        feed.subscribe(board)
        await commands.execute(CreateTask(CreateTaskBody("Wake the board")))
        await events.drain(timeout=1)
        assert board.messages == ["tasks_changed"]

        feed.unsubscribe(board)
        await commands.execute(CreateTask(CreateTaskBody("Nobody listens")))
        await events.drain(timeout=1)
        assert board.messages == ["tasks_changed"]
    finally:
        await application.close()


class _RecordingBoard:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_info(self, name: str, value: object = None) -> bool:
        del value
        self.messages.append(name)
        return True


def _mount_context() -> MountContext:
    return MountContext(
        request=None,
        params={},
        resource="/board",
        connected=False,
        query_params=QueryParams(""),
    )


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
