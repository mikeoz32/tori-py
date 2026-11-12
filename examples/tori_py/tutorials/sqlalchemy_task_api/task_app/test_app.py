"""Executable tests for the SQLAlchemy Task API tutorial."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingApplication as ToriTestingApplication
from tori_py.testing import TestingModule, http_client
from tori_py_sqlalchemy import SqlAlchemyModule

from .app import PIPELINE, AppModule, create_application
from .database import Base, database

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@asynccontextmanager
async def application_on(
    database_file: Path,
) -> AsyncIterator[ToriTestingApplication]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_file}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        builder = TestingModule.create(AppModule)
        builder.replace_module(database, SqlAlchemyModule.for_engine(engine))
        application = await builder.compile(
            adapter=StarletteAdapter(),
            pipeline=PIPELINE,
        )
        try:
            yield application
        finally:
            await application.close()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_http_contract_matches_part_one(tmp_path: Path) -> None:
    async with (
        application_on(tmp_path / "tasks.db") as application,
        http_client(application) as client,
    ):
        empty = await client.get("/tasks")
        assert empty.status_code == 200
        assert empty.json() == []

        for title in ("   ", "x" * 121):
            invalid_title = await client.post("/tasks", json={"title": title})
            _assert_problem(
                invalid_title,
                status_code=400,
                title="Bad Request",
                detail="After trimming, the task title must contain 1-120 characters.",
                instance="/tasks",
            )

        missing = await client.post("/tasks", json={})
        _assert_validation_problem(
            missing,
            parameter="body",
            source="body",
            message="Object missing required field `title`",
        )

        invalid_path = await client.get("/tasks/not-an-integer")
        _assert_validation_problem(
            invalid_path,
            parameter="task_id",
            source="path",
            message="invalid literal for int() with base 10: 'not-an-integer'",
            instance="/tasks/not-an-integer",
        )

        created = await client.post("/tasks", json={"title": "  Ship Part 1  "})
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


@pytest.mark.asyncio
async def test_batch_creation_is_atomic(tmp_path: Path) -> None:
    async with (
        application_on(tmp_path / "tasks.db") as application,
        http_client(application) as client,
    ):
        rejected = await client.post(
            "/tasks/batch",
            json={"titles": ["Plan the release", "   "]},
        )
        _assert_problem(
            rejected,
            status_code=400,
            title="Bad Request",
            detail="After trimming, the task title must contain 1-120 characters.",
            instance="/tasks/batch",
        )
        unchanged = await client.get("/tasks")
        assert unchanged.json() == []

        created = await client.post(
            "/tasks/batch",
            json={"titles": ["Plan the release", "  Write notes  "]},
        )
        assert created.status_code == 201
        assert created.json() == [
            {"id": 1, "title": "Plan the release"},
            {"id": 2, "title": "Write notes"},
        ]
        listed = await client.get("/tasks")
        assert listed.json() == created.json()


@pytest.mark.asyncio
async def test_migrations_create_the_model_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'tasks.db'}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=tmp_path,
        env={**os.environ, "TASK_API_DATABASE__URL": url},
        check=True,
        capture_output=True,
    )

    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            differences = await connection.run_sync(_schema_differences)
    finally:
        await engine.dispose()
    assert differences == []

    monkeypatch.setenv("TASK_API_DATABASE__URL", url)
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            created = await client.post("/tasks", json={"title": "Migrated"})
            assert created.status_code == 201
            assert (await client.get("/tasks")).json() == [created.json()]
    finally:
        await application.shutdown()


def _schema_differences(connection: Connection) -> list[object]:
    return compare_metadata(MigrationContext.configure(connection), Base.metadata)


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
    assert response.json() == {
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
