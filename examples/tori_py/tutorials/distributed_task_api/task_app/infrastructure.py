"""Small process bootstrap helpers shared by the tutorial applications."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable

from tori_py import NestApplication


def rabbitmq_url() -> str:
    """Return the configured broker endpoint without opening a connection."""

    return os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")


async def serve(factory: Callable[[], Awaitable[NestApplication]]) -> None:
    """Run one non-HTTP service until a process signal requests shutdown."""

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


__all__ = ["rabbitmq_url", "serve"]
