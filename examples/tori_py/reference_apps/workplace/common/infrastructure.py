"""Small, lazy infrastructure helpers shared by service composition roots."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable

from tori_py import DeferredModule, NestApplication
from tori_py_microservices import (
    MicroservicesModule,
    MicroservicesOptions,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    ServiceIdentity,
)
from tori_py_sqlalchemy import SqlAlchemyModule, SqlAlchemyOptions


def database_url(service: str) -> str:
    return os.getenv(
        f"WORKPLACE_{service.upper()}_DATABASE_URL", f"sqlite+aiosqlite:///{service}.db"
    )


def rabbitmq_url(service: str) -> str:
    return os.getenv(
        f"WORKPLACE_{service.upper()}_RABBITMQ_URL",
        os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/"),
    )


def sql_module(service: str) -> DeferredModule:
    return SqlAlchemyModule.for_root(SqlAlchemyOptions(url=database_url(service)))


def rabbit_modules(
    identity: ServiceIdentity,
) -> tuple[RabbitMqTransport, DeferredModule, DeferredModule]:
    transport = RabbitMqTransport()
    rabbit = RabbitMqModule.for_root(RabbitMqOptions(rabbitmq_url(identity.name)))
    service = MicroservicesModule.for_root(
        identity, transport=transport, imports=(rabbit,), options=MicroservicesOptions()
    )
    return transport, rabbit, service


async def serve(factory: Callable[[], Awaitable[NestApplication]]) -> None:
    """Start one compiled microservice and wait for a termination signal."""
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
