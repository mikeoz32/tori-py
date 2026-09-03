"""Native ASGI view over the framework-owned HTTP context."""

from __future__ import annotations

import contextvars
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from dataclasses import dataclass
from http.cookies import SimpleCookie
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qsl

from tori_py.http.context import (
    HttpContext,
    _reset_http_context,
    _set_http_context,
    current_http_context,
)

type AsgiScope = MutableMapping[str, Any]
type Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]


class _AsgiRequest:
    __slots__ = (
        "scope",
        "receive",
        "path_params",
        "body",
        "_cookies",
        "_headers",
        "_query",
        "on_handler_end",
        "on_handler_start",
    )

    def __init__(
        self,
        scope: AsgiScope,
        receive: Receive,
        path_params: Mapping[str, object],
    ) -> None:
        self.scope = scope
        self.receive = receive
        self.path_params = MappingProxyType(dict(path_params))
        self.body: object = _BODY_UNSET
        self._headers: tuple[tuple[str, str], ...] | None = None
        self._query: tuple[tuple[str, str], ...] | None = None
        self._cookies: Mapping[str, str] | None = None
        self.on_handler_end: Callable[[], None] = _noop
        self.on_handler_start: Callable[[], None] = _noop

    @property
    def method(self) -> str:
        return str(self.scope["method"])

    @property
    def path(self) -> str:
        return str(self.scope["path"])

    @property
    def headers(self) -> tuple[tuple[str, str], ...]:
        if self._headers is None:
            self._headers = tuple(
                (
                    bytes(name).decode("latin-1").casefold(),
                    bytes(value).decode("latin-1"),
                )
                for name, value in self.scope.get("headers", ())
            )
        return self._headers

    @property
    def query(self) -> tuple[tuple[str, str], ...]:
        if self._query is None:
            query_string = bytes(self.scope.get("query_string", b""))
            self._query = tuple(
                parse_qsl(
                    query_string.decode("latin-1"),
                    keep_blank_values=True,
                )
            )
        return self._query

    @property
    def cookies(self) -> Mapping[str, str]:
        if self._cookies is None:
            parsed: SimpleCookie[str] = SimpleCookie()
            for value in self.header_values("cookie"):
                parsed.load(value)
            self._cookies = MappingProxyType(
                {name: morsel.value for name, morsel in parsed.items()}
            )
        return self._cookies

    def header_values(self, name: str) -> list[str]:
        normalized = name.casefold()
        return [value for key, value in self.headers if key == normalized]

    def query_values(self, name: str) -> list[str]:
        return [value for key, value in self.query if key == name]


@dataclass(frozen=True, slots=True)
class RequestContext(HttpContext):
    """HTTP execution context exposing the native ASGI request scope."""

    request: _AsgiRequest

    @property
    def metadata(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "method": self.method,
                "path": self.path,
                "headers": self.headers,
                "query": self.query_params,
                "path_params": self.path_params,
            }
        )

    @property
    def asgi_scope(self) -> Mapping[str, object]:
        return MappingProxyType(self.request.scope)

    @property
    def method(self) -> str:
        return self.request.method

    @property
    def path(self) -> str:
        return self.request.path

    @property
    def headers(self) -> tuple[tuple[str, str], ...]:
        return self.request.headers

    @property
    def query_params(self) -> tuple[tuple[str, str], ...]:
        return self.request.query

    @property
    def path_params(self) -> Mapping[str, object]:
        return self.request.path_params

    @property
    def cookies(self) -> Mapping[str, str]:
        return self.request.cookies


def current_request_context() -> RequestContext | None:
    context = current_http_context()
    return context if isinstance(context, RequestContext) else None


def _set_context(
    context: RequestContext | None,
) -> contextvars.Token[HttpContext | None]:
    return _set_http_context(context)


def _reset_context(token: contextvars.Token[HttpContext | None]) -> None:
    _reset_http_context(token)


_BODY_UNSET = object()


def _noop() -> None:
    return None


__all__ = ["RequestContext", "current_request_context"]
