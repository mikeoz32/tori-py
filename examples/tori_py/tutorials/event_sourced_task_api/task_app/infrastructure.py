"""Production RabbitMQ configuration and process lifecycle helpers."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable

from tori_py import NestApplication
from tori_py_persistent_streams_rabbitmq import (
    RabbitMqConnectionOptions,
    RabbitMqPersistentStreamsOptions,
)


def rabbitmq_amqp_url() -> str:
    """Return the AMQP endpoint used by typed RPC transports."""

    return os.getenv(
        "RABBITMQ_URL",
        "amqp://tutorial:tutorial@localhost:5672/",
    )


def rabbitmq_stream_options(
    connection_name: str,
) -> RabbitMqPersistentStreamsOptions:
    """Return native RabbitMQ Streams connection options."""

    connection = RabbitMqConnectionOptions(
        host=os.getenv("RABBITMQ_STREAM_HOST", "localhost"),
        port=int(os.getenv("RABBITMQ_STREAM_PORT", "5552")),
        username=os.getenv("RABBITMQ_USER", "tutorial"),
        password=os.getenv("RABBITMQ_PASSWORD", "tutorial"),
        connection_name=connection_name,
    )
    return RabbitMqPersistentStreamsOptions(connection)


async def serve(factory: Callable[[], Awaitable[NestApplication]]) -> None:
    """Run one non-HTTP application until process shutdown is requested."""

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


__all__ = ["rabbitmq_amqp_url", "rabbitmq_stream_options", "serve"]
