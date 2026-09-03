"""Shared Tori Py implementation of the benchmark endpoints."""

from __future__ import annotations

from typing import Annotated

from tori_py import (
    HttpResponse,
    Inject,
    Scope,
    controller,
    get,
    injectable,
    module,
)

from tori_py_benchmarks.apps.common import HEALTH_RESPONSE, HELLO_BYTES, JSON_RESPONSE


@injectable()
class First:
    def __init__(self) -> None:
        self.value = 5


@injectable()
class Second:
    def __init__(self, first: First) -> None:
        self.first = first


@injectable()
class Third:
    def __init__(self, second: Second) -> None:
        self.second = second


@injectable()
class Fourth:
    def __init__(self, third: Third) -> None:
        self.third = third


@injectable()
class Fifth:
    def __init__(self, fourth: Fourth) -> None:
        self.fourth = fourth

    @property
    def value(self) -> int:
        return self.fourth.third.second.first.value


@injectable(scope=Scope.REQUEST)
class RequestFirst:
    def __init__(self) -> None:
        self.value = 5


@injectable(scope=Scope.REQUEST)
class RequestSecond:
    def __init__(self, first: RequestFirst) -> None:
        self.first = first


@injectable(scope=Scope.REQUEST)
class RequestThird:
    def __init__(self, second: RequestSecond) -> None:
        self.second = second


@injectable(scope=Scope.REQUEST)
class RequestFourth:
    def __init__(self, third: RequestThird) -> None:
        self.third = third


@injectable(scope=Scope.REQUEST)
class RequestFifth:
    def __init__(self, fourth: RequestFourth) -> None:
        self.fourth = fourth

    @property
    def value(self) -> int:
        return self.fourth.third.second.first.value


@controller()
class BenchmarkController:
    def __init__(self, fifth: Fifth) -> None:
        self.fifth = fifth

    @get("/health")
    async def health(self) -> dict[str, str]:
        return HEALTH_RESPONSE

    @get("/plaintext")
    async def plaintext(self) -> HttpResponse:
        return HttpResponse(HELLO_BYTES, headers={"content-type": "text/plain"})

    @get("/json")
    async def json_response(self) -> dict[str, str]:
        return JSON_RESPONSE

    @get("/singleton")
    async def singleton(self) -> dict[str, int]:
        return {"value": self.fifth.value}

    @get("/inject")
    async def inject(
        self, fifth: Annotated[RequestFifth, Inject(RequestFifth)]
    ) -> dict[str, int]:
        return {"value": fifth.value}


@module(
    providers=[
        First,
        Second,
        Third,
        Fourth,
        Fifth,
        RequestFirst,
        RequestSecond,
        RequestThird,
        RequestFourth,
        RequestFifth,
    ],
    controllers=[BenchmarkController],
)
class BenchmarkModule:
    pass
