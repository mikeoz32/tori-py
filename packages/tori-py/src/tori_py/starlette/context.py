"""Starlette-native view over the framework-owned HTTP context."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from types import MappingProxyType

from starlette.requests import Request

from tori_py.http.context import (
    HttpContext,
    _reset_http_context,
    _set_http_context,
    current_http_context,
)


@dataclass(frozen=True, slots=True)
class RequestContext(HttpContext):
    """HTTP execution context exposing the native Starlette request."""

    request: Request

    @property
    def metadata(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "method": self.request.method,
                "path": self.request.url.path,
                "headers": self.request.headers,
                "query": self.request.query_params,
                "path_params": self.request.path_params,
            }
        )

    @property
    def method(self) -> str:
        return self.request.method

    @property
    def path(self) -> str:
        return self.request.url.path

    @property
    def headers(self):
        return self.request.headers

    @property
    def query_params(self):
        return self.request.query_params

    @property
    def path_params(self):
        return self.request.path_params

    @property
    def cookies(self):
        return self.request.cookies


def current_request_context() -> RequestContext | None:
    context = current_http_context()
    return context if isinstance(context, RequestContext) else None


def _set_context(
    context: RequestContext,
) -> contextvars.Token[HttpContext | None]:
    return _set_http_context(context)


def _reset_context(token: contextvars.Token[HttpContext | None]) -> None:
    _reset_http_context(token)


__all__ = [
    "RequestContext",
    "current_request_context",
]
