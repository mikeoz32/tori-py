"""Minimal ASGI implementation of the benchmark endpoints."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from tori_py_benchmarks.apps.common import (
    HELLO_BYTES,
    PREBUILT_DEPENDENCY,
    resolve_request_dependency,
)

ASGISend = Callable[[dict[str, Any]], Awaitable[None]]


async def application(
    scope: dict[str, Any],
    receive: Callable[[], Awaitable[dict[str, Any]]],
    send: ASGISend,
) -> None:
    if scope["type"] == "lifespan":
        await _handle_lifespan(receive, send)
        return
    if scope["type"] != "http":
        return

    path = scope["path"]
    if scope["method"] != "GET":
        await _send_response(send, 404, b"", b"text/plain")
    elif path == "/health":
        await _send_response(send, 200, b'{"status":"ok"}', b"application/json")
    elif path == "/plaintext":
        await _send_response(send, 200, HELLO_BYTES, b"text/plain")
    elif path == "/json":
        await _send_response(
            send,
            200,
            b'{"message":"Hello, World!"}',
            b"application/json",
        )
    elif path == "/singleton":
        body = f'{{"value":{PREBUILT_DEPENDENCY.value}}}'.encode()
        await _send_response(send, 200, body, b"application/json")
    elif path == "/inject":
        body = f'{{"value":{resolve_request_dependency().value}}}'.encode()
        await _send_response(send, 200, body, b"application/json")
    else:
        await _send_response(send, 404, b"", b"text/plain")


async def _handle_lifespan(
    receive: Callable[[], Awaitable[dict[str, Any]]], send: ASGISend
) -> None:
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


async def _send_response(
    send: ASGISend, status: int, body: bytes, content_type: bytes
) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", content_type),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
