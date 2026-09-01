"""PostgreSQL specifications for booking exclusion and transaction atomicity."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from tori_py_microservices import EventDispatcher
from tori_py_sqlalchemy import EntityManager

from examples.tori_py.reference_apps.workplace.bookings.app import (
    AuditRepository,
    AuditRow,
    BookingConflict,
    BookingRepository,
    BookingRow,
    CreateBookingCommand,
    CreateBookingHandler,
    OutboxRelay,
    OutboxRepository,
    OutboxRow,
)
from examples.tori_py.reference_apps.workplace.bookings.migrate import migrate

pytest.importorskip("psycopg")
pytest.importorskip("pytest_docker")


@pytest.fixture(scope="session")
def docker_compose_file() -> str:
    return str(Path(__file__).with_name("docker-compose.yml"))


@pytest.fixture
def postgres_url(docker_services, docker_ip: str) -> str:
    port = docker_services.port_for("postgres", 5432)
    url = f"postgresql+psycopg://postgres:postgres@{docker_ip}:{port}/postgres"
    readiness_url = f"postgresql://postgres:postgres@{docker_ip}:{port}/postgres"

    def is_ready() -> bool:
        psycopg = __import__("psycopg")

        try:
            with psycopg.connect(readiness_url):
                return True
        except psycopg.OperationalError:
            return False

    docker_services.wait_until_responsive(is_ready, timeout=30, pause=0.5)
    return url


@pytest.fixture
async def migrated_postgres(postgres_url: str, monkeypatch: pytest.MonkeyPatch):
    """Run the production migration against an isolated schema in PostgreSQL."""
    schema = f"booking_test_{uuid4().hex}"
    engine = create_async_engine(postgres_url)
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await engine.dispose()

    database_url = f"{postgres_url}?options=-csearch_path%3D{schema}"
    monkeypatch.setenv("WORKPLACE_BOOKINGS_DATABASE_URL", database_url)
    try:
        await migrate()
        yield database_url
    finally:
        cleanup_engine = create_async_engine(postgres_url)
        try:
            async with cleanup_engine.begin() as connection:
                await connection.execute(
                    text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                )
        finally:
            await cleanup_engine.dispose()


def _handler(database_url: str) -> tuple[CreateBookingHandler, AsyncEngine]:
    engine = create_async_engine(database_url)
    entities = EntityManager(async_sessionmaker(engine, expire_on_commit=False))
    bookings = BookingRepository(BookingRow, entities)
    outbox = OutboxRepository(OutboxRow, entities)
    audit = AuditRepository(AuditRow, entities)
    return CreateBookingHandler(entities, bookings, outbox, audit), engine


def _command(tenant_id: str, idempotency_key: str) -> CreateBookingCommand:
    starts_at = datetime(2026, 9, 2, 9, tzinfo=UTC)
    return CreateBookingCommand(
        tenant_id=tenant_id,
        actor_id=f"employee-{idempotency_key}",
        resource_id="desk-17",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        idempotency_key=idempotency_key,
    )


async def _submit(
    handler: CreateBookingHandler, command: CreateBookingCommand
) -> object:
    try:
        return await handler.handle(command)
    except BookingConflict as error:
        return error


async def _row_counts(database_url: str) -> tuple[int, int, int]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            counts: list[int] = []
            for table in ("bookings", "outbox", "booking_audit"):
                statement = text(f"SELECT count(*) FROM {table}")
                counts.append(int(await connection.scalar(statement) or 0))
            return counts[0], counts[1], counts[2]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_exclusion_constraint_makes_concurrent_overlap_atomic(
    migrated_postgres: str,
) -> None:
    first, first_engine = _handler(migrated_postgres)
    second, second_engine = _handler(migrated_postgres)
    try:
        results = await asyncio.gather(
            _submit(first, _command("tenant-north", "first")),
            _submit(second, _command("tenant-north", "second")),
        )
        successes = [result for result in results if not isinstance(result, Exception)]
        conflicts = [
            result for result in results if isinstance(result, BookingConflict)
        ]

        assert len(successes) == 1
        assert len(conflicts) == 1
        assert await _row_counts(migrated_postgres) == (1, 1, 1)
    finally:
        await first_engine.dispose()
        await second_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_overlap_is_isolated_by_tenant(
    migrated_postgres: str,
) -> None:
    north, north_engine = _handler(migrated_postgres)
    south, south_engine = _handler(migrated_postgres)
    try:
        results = await asyncio.gather(
            _submit(north, _command("tenant-north", "north")),
            _submit(south, _command("tenant-south", "south")),
        )

        assert not any(isinstance(result, Exception) for result in results)
        assert await _row_counts(migrated_postgres) == (2, 2, 2)
    finally:
        await north_engine.dispose()
        await south_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_outbox_claim_allows_only_one_concurrent_publisher(
    migrated_postgres: str,
) -> None:
    create, create_engine = _handler(migrated_postgres)
    await create.handle(_command("tenant-north", "outbox-claim"))

    class BlockingEvents:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.event_ids: list[str] = []

        async def publish(self, *args, **kwargs) -> None:
            self.event_ids.append(kwargs["headers"]["outbox_event_id"])
            self.started.set()
            await self.release.wait()

    events = BlockingEvents()
    first_engine = create_async_engine(migrated_postgres)
    second_engine = create_async_engine(migrated_postgres)
    first_entities = EntityManager(
        async_sessionmaker(first_engine, expire_on_commit=False)
    )
    second_entities = EntityManager(
        async_sessionmaker(second_engine, expire_on_commit=False)
    )
    first_outbox = OutboxRepository(OutboxRow, first_entities)
    second_outbox = OutboxRepository(OutboxRow, second_entities)
    first = OutboxRelay(first_entities, first_outbox, cast(EventDispatcher, events))
    second = OutboxRelay(second_entities, second_outbox, cast(EventDispatcher, events))

    try:
        publication = asyncio.create_task(first.publish_once())
        await asyncio.wait_for(events.started.wait(), timeout=5)
        assert await asyncio.wait_for(second.publish_once(), timeout=1) is False
        events.release.set()
        assert await publication is True
        assert len(events.event_ids) == 1

        row = await first_outbox.find_one(OutboxRow.tenant_id == "tenant-north")
        assert row is not None
        assert row.published_at is not None
    finally:
        events.release.set()
        await create_engine.dispose()
        await first_engine.dispose()
        await second_engine.dispose()
