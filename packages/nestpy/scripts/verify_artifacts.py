"""Smoke-test Nestpy wheel and source distributions in isolated uv runs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SMOKE = r"""
import asyncio
import json
from typing import Annotated

from nestpy import Query, controller, get, module
from nestpy.starlette import NestApplication

@controller()
class Controller:
    @get("/health")
    async def health(self, value: Annotated[str, Query("value")]) -> dict[str, str]:
        return {"status": "ok", "value": value}

@module(controllers=[Controller])
class Root:
    pass

async def smoke() -> None:
    application = await NestApplication.create(Root)
    await application.start()
    messages = []
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    try:
        await application.http_app(
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


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_artifacts.py DIST_DIR")
    dist = Path(sys.argv[1]).resolve()
    artifacts = sorted(dist.glob("nestpy-*.whl")) + sorted(dist.glob("nestpy-*.tar.gz"))
    if not artifacts:
        raise SystemExit(f"no Nestpy artifacts found in {dist}")
    uv = "uv"
    for artifact in artifacts:
        command = [
            uv,
            "run",
            "--isolated",
            "--with",
            str(artifact),
            "python",
            "-c",
            SMOKE,
        ]
        completed = subprocess.run(command, check=False, text=True)
        if completed.returncode:
            raise SystemExit(f"artifact smoke failed: {artifact.name}")


if __name__ == "__main__":
    main()
