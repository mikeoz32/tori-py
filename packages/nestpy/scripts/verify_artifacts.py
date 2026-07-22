"""Smoke-test Nestpy wheel and source distributions in isolated uv runs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SMOKE = r"""
import asyncio
import importlib.util
import json
from typing import Annotated

from nestpy import NestApplication, Query, controller, get, module
from nestpy.starlette import StarletteAdapter

assert importlib.util.find_spec("httpx") is None

@controller()
class Controller:
    @get("/health")
    async def health(self, value: Annotated[str, Query("value")]) -> dict[str, str]:
        return {"status": "ok", "value": value}

@module(controllers=[Controller])
class Root:
    pass

async def smoke() -> None:
    adapter = StarletteAdapter()
    application = await NestApplication.create(Root, adapter=adapter)
    await application.start()
    messages = []
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")
        sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    try:
        await adapter.app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/health",
                "raw_path": b"/health",
                "query_string": b"value=artifact",
                "headers": [],
                "client": ("test", 1),
                "server": ("test", 80),
            },
            receive,
            send,
        )
    finally:
        await application.shutdown()
    assert messages[0]["status"] == 200
    assert json.loads(messages[1]["body"]) == {
        "status": "ok",
        "value": "artifact",
    }

asyncio.run(smoke())
"""

HTTPX_SMOKE = r"""
import asyncio

from nestpy import controller, get, module
from nestpy.starlette import StarletteAdapter
from nestpy.testing import TestingModule

@controller()
class Controller:
    @get("/health")
    async def health(self) -> dict[str, str]:
        return {"status": "ok"}

@module(controllers=[Controller])
class Root:
    pass

async def smoke() -> None:
    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    try:
        async with application.http_client() as client:
            response = await client.get("/health")
    finally:
        await application.close()
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

asyncio.run(smoke())
"""


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_artifacts.py DIST_DIR")
    dist = Path(sys.argv[1]).resolve()
    artifacts = sorted(dist.glob("nestpy-*.whl")) + sorted(dist.glob("nestpy-*.tar.gz"))
    if not artifacts:
        raise SystemExit(f"no Nestpy artifacts found in {dist}")
    uv = "uv"
    for artifact in artifacts:
        smoke_tests = (
            (str(artifact), "base", SMOKE),
            (f"{artifact}[testing]", "testing extra", HTTPX_SMOKE),
        )
        for requirement, name, smoke in smoke_tests:
            command = [
                uv,
                "run",
                "--isolated",
                "--no-project",
                "--with",
                requirement,
                "python",
                "-c",
                smoke,
            ]
            completed = subprocess.run(command, check=False, text=True)
            if completed.returncode:
                raise SystemExit(f"artifact {name} smoke failed: {artifact.name}")


if __name__ == "__main__":
    main()
