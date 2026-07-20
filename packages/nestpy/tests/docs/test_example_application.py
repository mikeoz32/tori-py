import asyncio
import json
from typing import cast

import pytest
from nestpy.starlette import StarletteAdapter
from starlette.types import Message

from examples.nestpy.app import create_application


@pytest.mark.asyncio
async def test_documented_example_serves_one_request() -> None:
    application = await create_application()
    await application.start()
    http_app = application.get_adapter(StarletteAdapter).app
    messages: list[dict[str, object]] = []
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")
        sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        messages.append(dict(message))

    try:
        await http_app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/example/health",
                "raw_path": b"/example/health",
                "query_string": b"count=2",
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
    assert json.loads(cast(bytes, messages[1]["body"])) == {
        "status": "hello",
        "count": 2,
        "request_value": "request",
    }
