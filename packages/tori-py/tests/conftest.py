from collections.abc import Awaitable, Callable
from typing import cast

import httpx
import pytest
from starlette.types import ASGIApp

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
        transport = httpx.ASGITransport(
            app=cast(ASGIApp, app),
            raise_app_exceptions=False,
            client=("test", 1),
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            response = await client.request(
                method,
                path,
                content=body,
                headers=headers,
            )
        return [
            {
                "type": "http.response.start",
                "status": response.status_code,
                "headers": response.headers.raw,
            },
            {
                "type": "http.response.body",
                "body": response.content,
            },
        ]

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
