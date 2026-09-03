"""FastAPI implementation of the benchmark endpoints."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import PlainTextResponse

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


@lru_cache
def provide_first() -> First:
    return First()


@lru_cache
def provide_second(first: Annotated[First, Depends(provide_first)]) -> Second:
    return Second(first)


@lru_cache
def provide_third(second: Annotated[Second, Depends(provide_second)]) -> Third:
    return Third(second)


@lru_cache
def provide_fourth(third: Annotated[Third, Depends(provide_third)]) -> Fourth:
    return Fourth(third)


@lru_cache
def provide_fifth(fourth: Annotated[Fourth, Depends(provide_fourth)]) -> Fifth:
    return Fifth(fourth)


def provide_request_first() -> First:
    return First()


def provide_request_second(
    first: Annotated[First, Depends(provide_request_first)],
) -> Second:
    return Second(first)


def provide_request_third(
    second: Annotated[Second, Depends(provide_request_second)],
) -> Third:
    return Third(second)


def provide_request_fourth(
    third: Annotated[Third, Depends(provide_request_third)],
) -> Fourth:
    return Fourth(third)


def provide_request_fifth(
    fourth: Annotated[Fourth, Depends(provide_request_fourth)],
) -> Fifth:
    return Fifth(fourth)


application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)


@application.get("/health")
async def health() -> dict[str, str]:
    return HEALTH_RESPONSE


@application.get("/plaintext", response_class=PlainTextResponse)
async def plaintext() -> str:
    return HELLO_TEXT


@application.get("/json")
async def json_response() -> dict[str, str]:
    return JSON_RESPONSE


# https://fastapi.tiangolo.com/tutorial/dependencies/
@application.get("/singleton")
async def singleton(fifth: Annotated[Fifth, Depends(provide_fifth)]) -> dict[str, int]:
    return {"value": fifth.value}


@application.get("/inject")
async def inject(
    fifth: Annotated[Fifth, Depends(provide_request_fifth)],
) -> dict[str, int]:
    return {"value": fifth.value}
