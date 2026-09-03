"""Litestar implementation of the benchmark endpoints."""

from __future__ import annotations

from litestar import Litestar, get
from litestar.di import NamedDependency, Provide
from litestar.response import Response

from tori_py_benchmarks.apps.common import (
    HEALTH_RESPONSE,
    HELLO_TEXT,
    JSON_RESPONSE,
    Fifth,
    First,
    Fourth,
    Second,
    Third,
)


def provide_first() -> First:
    return First()


def provide_second(first: NamedDependency[First]) -> Second:
    return Second(first)


def provide_third(second: NamedDependency[Second]) -> Third:
    return Third(second)


def provide_fourth(third: NamedDependency[Third]) -> Fourth:
    return Fourth(third)


def provide_fifth(fourth: NamedDependency[Fourth]) -> Fifth:
    return Fifth(fourth)


def provide_request_first() -> First:
    return First()


def provide_request_second(request_first: NamedDependency[First]) -> Second:
    return Second(request_first)


def provide_request_third(request_second: NamedDependency[Second]) -> Third:
    return Third(request_second)


def provide_request_fourth(request_third: NamedDependency[Third]) -> Fourth:
    return Fourth(request_third)


def provide_request_fifth(request_fourth: NamedDependency[Fourth]) -> Fifth:
    return Fifth(request_fourth)


@get("/health")
async def health() -> dict[str, str]:
    return HEALTH_RESPONSE


@get("/plaintext")
async def plaintext() -> Response[str]:
    return Response(HELLO_TEXT, media_type="text/plain")


@get("/json")
async def json_response() -> dict[str, str]:
    return JSON_RESPONSE


# https://docs.litestar.dev/latest/usage/dependency-injection.html
@get("/singleton")
async def singleton(fifth: NamedDependency[Fifth]) -> dict[str, int]:
    return {"value": fifth.value}


@get("/inject")
async def inject(request_fifth: NamedDependency[Fifth]) -> dict[str, int]:
    return {"value": request_fifth.value}


application = Litestar(
    route_handlers=[health, plaintext, json_response, singleton, inject],
    dependencies={
        "first": Provide(provide_first, use_cache=True, sync_to_thread=False),
        "second": Provide(provide_second, use_cache=True, sync_to_thread=False),
        "third": Provide(provide_third, use_cache=True, sync_to_thread=False),
        "fourth": Provide(provide_fourth, use_cache=True, sync_to_thread=False),
        "fifth": Provide(provide_fifth, use_cache=True, sync_to_thread=False),
        "request_first": Provide(provide_request_first, sync_to_thread=False),
        "request_second": Provide(provide_request_second, sync_to_thread=False),
        "request_third": Provide(provide_request_third, sync_to_thread=False),
        "request_fourth": Provide(provide_request_fourth, sync_to_thread=False),
        "request_fifth": Provide(provide_request_fifth, sync_to_thread=False),
    },
    openapi_config=None,
)
