"""Shared composition helpers for the example processes."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable, Iterable

from nestpy import DeferredModule, ModuleImport, NestApplication
from nestpy_microservices import (
    MicroservicesModule,
    MicroservicesOptions,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    ServiceIdentity,
)
from nestpy_sqlalchemy import SqlAlchemyModule, SqlAlchemyOptions
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import create_async_engine


def database_url(service: str) -> str:
    """Read one service-owned database URL from the environment."""

    return os.getenv(
        f"{service.upper()}_DATABASE_URL",
        f"sqlite+aiosqlite:///{service}.db",
    )


def rabbitmq_url() -> str:
    return os.getenv("RABBITMQ_URL", "amqp://demo:demo@localhost:5672/")


def sql_module(url: str) -> DeferredModule:
    return SqlAlchemyModule.for_root(SqlAlchemyOptions(url=url))


def rabbit_modules(
    identity: ServiceIdentity,
    *,
    imports: Iterable[ModuleImport] = (),
) -> tuple[RabbitMqTransport, DeferredModule, DeferredModule]:
    """Return one adapter reference, RabbitMQ root, and service root."""

    reference = RabbitMqTransport()
    rabbit = RabbitMqModule.for_root(RabbitMqOptions(rabbitmq_url()))
    service = MicroservicesModule.for_root(
        identity,
        transport=reference,
        imports=(rabbit, *tuple(imports)),
        options=MicroservicesOptions(),
    )
    return reference, rabbit, service


async def migrate(metadata: MetaData, url: str) -> None:
    """Apply the small demo schema from a dedicated migration job."""

    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
    finally:
        await engine.dispose()


async def serve(factory: Callable[[], Awaitable[NestApplication]]) -> None:
    """Run one service until a process signal requests graceful shutdown."""

    application = await factory()
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for process_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(process_signal, stopped.set)
        except NotImplementedError:
            pass
    await application.start()
    try:
        await stopped.wait()
    finally:
        await application.shutdown()


__all__ = [
    "database_url",
    "migrate",
    "rabbit_modules",
    "rabbitmq_url",
    "serve",
    "sql_module",
]
