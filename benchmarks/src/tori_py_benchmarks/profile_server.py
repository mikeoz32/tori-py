"""Run one benchmark application under cProfile with controlled shutdown."""

from __future__ import annotations

import argparse
import cProfile
import importlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import uvicorn

_SHUTDOWN_PATH = "/__tori_py_benchmark_shutdown__"
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
AsgiApplication = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]


class _ProfiledApplication:
    def __init__(self, application: AsgiApplication) -> None:
        self.application = application
        self.server: uvicorn.Server | None = None

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] == "http" and scope["path"] == _SHUTDOWN_PATH:
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            assert self.server is not None
            self.server.should_exit = True
            return
        await self.application(scope, receive, send)


def main() -> None:
    arguments = _parse_arguments()
    module_name, attribute = arguments.application.rsplit(":", 1)
    application = getattr(importlib.import_module(module_name), attribute)
    profiled_application = _ProfiledApplication(application)
    server = uvicorn.Server(
        uvicorn.Config(
            profiled_application,
            host="127.0.0.1",
            port=arguments.port,
            loop="asyncio",
            http="httptools",
            lifespan="on",
            log_level="warning",
            access_log=False,
            server_header=False,
        )
    )
    profiled_application.server = server
    profiler = cProfile.Profile()
    try:
        profiler.runcall(server.run)
    finally:
        profiler.dump_stats(arguments.profile)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--application", required=True)
    parser.add_argument("--port", type=int, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    main()
