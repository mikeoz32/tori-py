"""Starlette implementation of the benchmark endpoints."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from tori_py_benchmarks.apps.common import (
    HEALTH_RESPONSE,
    HELLO_TEXT,
    JSON_RESPONSE,
    PREBUILT_DEPENDENCY,
    resolve_request_dependency,
)


# https://www.starlette.io/routing/
async def health(request: Request) -> JSONResponse:
    del request
    return JSONResponse(HEALTH_RESPONSE)


async def plaintext(request: Request) -> PlainTextResponse:
    del request
    return PlainTextResponse(HELLO_TEXT)


async def json_response(request: Request) -> JSONResponse:
    del request
    return JSONResponse(JSON_RESPONSE)


async def singleton(request: Request) -> JSONResponse:
    del request
    return JSONResponse({"value": PREBUILT_DEPENDENCY.value})


async def inject(request: Request) -> JSONResponse:
    del request
    return JSONResponse({"value": resolve_request_dependency().value})


application = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/plaintext", plaintext, methods=["GET"]),
        Route("/json", json_response, methods=["GET"]),
        Route("/singleton", singleton, methods=["GET"]),
        Route("/inject", inject, methods=["GET"]),
    ]
)
