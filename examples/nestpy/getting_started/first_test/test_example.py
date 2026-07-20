"""The same public TestingModule workflow shown in the guide."""

import asyncio

import pytest
from nestpy.starlette import StarletteAdapter
from nestpy.testing import TestingModule
from starlette.types import Message

from examples.nestpy.getting_started.first_test.app import GREETING, AppModule


@pytest.mark.asyncio
async def test_exported_provider_can_be_overridden() -> None:
    builder = TestingModule.create(AppModule)
    builder.override_provider(GREETING, module=AppModule).use_value("Hello from test")
    application = await builder.compile(adapter=StarletteAdapter())
    messages: list[dict[str, object]] = []
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")
        sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        messages.append(dict(message))

    try:
        await application.get_adapter(StarletteAdapter).app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/greeting",
                "raw_path": b"/greeting",
                "query_string": b"",
                "headers": [],
                "client": ("test", 1),
                "server": ("test", 80),
            },
            receive,
            send,
        )
    finally:
        await application.close()
    assert messages[0]["status"] == 200
    assert messages[1]["body"] == b'{"message":"Hello from test"}'
