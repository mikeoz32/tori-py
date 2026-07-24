"""Acceptance tests for the non-CQRS Nestpy SQLAlchemy example."""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest
from nestpy.testing import http_client

from examples.nestpy.reference_apps.sqlalchemy_task_api.app import (
    MAX_DATABASE_TITLE_LENGTH,
    TaskApiSettings,
    create_application,
)


def _database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


@pytest.mark.asyncio
async def test_sqlalchemy_task_api_persistence_and_error_transactions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "SQLALCHEMY_TASK_API_DATABASE__URL",
        _database_url(tmp_path / "tasks.db"),
    )
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            created = await client.post("/tasks", json={"title": "Write example"})
            listed = await client.get("/tasks")
            found = await client.get("/tasks/1")
            duplicate = await client.post(
                "/tasks",
                json={"title": "Write example"},
            )
            after_duplicate = await client.get("/tasks")
            missing = await client.get("/tasks/999")
            invalid_title = await client.post(
                "/tasks",
                json={"title": "   "},
            )
            invalid_body = await client.post(
                "/tasks",
                json={"title": "", "unexpected": True},
            )
    finally:
        await application.shutdown()

    expected = {"id": 1, "title": "Write example"}
    assert created.status_code == 201
    assert created.json() == expected
    assert listed.status_code == 200
    assert listed.json() == [expected]
    assert found.status_code == 200
    assert found.json() == expected
    assert duplicate.status_code == 409
    assert duplicate.headers["content-type"].startswith("application/problem+json")
    assert duplicate.json() == {
        "type": "about:blank",
        "title": "Conflict",
        "status": 409,
        "detail": "A task with this title already exists.",
        "instance": "/tasks",
    }
    assert after_duplicate.json() == [expected]
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.json()["status"] == 404
    assert invalid_title.status_code == 400
    assert invalid_title.json()["status"] == 400
    assert invalid_body.status_code == 400
    assert invalid_body.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_failed_concurrent_request_does_not_rollback_other_requests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "SQLALCHEMY_TASK_API_DATABASE__URL",
        _database_url(tmp_path / "concurrent.db"),
    )
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            seeded = await client.post("/tasks", json={"title": "Duplicate"})
            responses = await asyncio.gather(
                client.post("/tasks", json={"title": "Duplicate"}),
                *(
                    client.post("/tasks", json={"title": f"Task {index}"})
                    for index in range(8)
                ),
            )
            listed = await client.get("/tasks")
    finally:
        await application.shutdown()

    assert seeded.status_code == 201
    assert responses[0].status_code == 409
    assert all(response.status_code == 201 for response in responses[1:])
    assert {task["title"] for task in listed.json()} == {
        "Duplicate",
        *(f"Task {index}" for index in range(8)),
    }


@pytest.mark.parametrize("value", [0, MAX_DATABASE_TITLE_LENGTH + 1])
def test_configured_title_limit_cannot_exceed_schema(value: int) -> None:
    with pytest.raises(ValueError, match="max_title_length"):
        TaskApiSettings(max_title_length=value)


def test_sqlalchemy_task_api_imports_no_cqrs_packages() -> None:
    script = """
import sys
import examples.nestpy.reference_apps.sqlalchemy_task_api.app

for name in (
    'cqrs_core',
    'cqrs_event_sourcing',
    'nestpy_cqrs',
    'nestpy_cqrs_event_sourcing',
):
    assert name not in sys.modules, name
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
