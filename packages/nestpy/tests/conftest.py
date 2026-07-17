from collections.abc import Awaitable, Callable
from typing import cast

import pytest
from starlette.types import ASGIApp, Message

type HttpCall = Callable[..., Awaitable[list[dict[str, object]]]]
type MessageBody = Callable[[dict[str, object]], bytes]
type MessageHeaders = Callable[[dict[str, object]], list[tuple[bytes, bytes]]]


@pytest.fixture
def call_http() -> HttpCall:
    async def call(
        app: Callable[..., Awaitable[None]],
        *,
        method: str = "GET",
        path: str = "/",
        body: bytes = b"",
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> list[dict[str, object]]:
        messages: list[dict[str, object]] = []
        sent = False

        async def receive() -> Message:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }

        async def send(message: Message) -> None:
            messages.append(dict(message))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path.split("?", 1)[0],
            "raw_path": path.encode(),
            "query_string": (path.split("?", 1)[1].encode() if "?" in path else b""),
            "headers": headers or [],
            "client": ("test", 1),
            "server": ("test", 80),
        }
        await cast(ASGIApp, app)(scope, receive, send)
        return messages

    return call


@pytest.fixture
def message_body() -> MessageBody:
    return lambda message: cast(bytes, message["body"])


@pytest.fixture
def message_headers() -> MessageHeaders:
    return lambda message: cast(
        list[tuple[bytes, bytes]],
        message["headers"],
    )
