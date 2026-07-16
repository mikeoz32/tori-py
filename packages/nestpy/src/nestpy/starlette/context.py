"""Starlette request context and request-scope correlation storage."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from starlette.requests import Request

from nestpy.core.compiler import ModuleId
from nestpy.core.protocols import ScopedResolver

if TYPE_CHECKING:
    from nestpy.core.runtime import RequestScope


_CURRENT_SCOPE: contextvars.ContextVar[RequestScope | None] = contextvars.ContextVar(
    "nestpy_request_scope",
    default=None,
)
_CURRENT_CONTEXT: contextvars.ContextVar[RequestContext | None] = (
    contextvars.ContextVar("nestpy_request_context", default=None)
)


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Driver-neutral execution context with an explicit Starlette request."""

    request: Request
    scope: RequestScope
    module_identity: ModuleId
    application: str
    route: str | None
    request_id_value: str

    @property
    def application_id(self) -> str:
        return self.application

    @property
    def module_id(self) -> str | None:
        return _module_label(self.module_identity)

    @property
    def route_id(self) -> str | None:
        return self.route

    @property
    def request_id(self) -> str | None:
        return self.request_id_value

    @property
    def resolver(self) -> ScopedResolver:
        return self.scope.resolver_for(self.module_identity)

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
    def execution_kind(self) -> str:
        return "http"

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


def current_request_scope() -> RequestScope | None:
    return _CURRENT_SCOPE.get()


def current_request_context() -> RequestContext | None:
    return _CURRENT_CONTEXT.get()


def _set_scope(scope: RequestScope) -> contextvars.Token[RequestScope | None]:
    return _CURRENT_SCOPE.set(scope)


def _reset_scope(token: contextvars.Token[RequestScope | None]) -> None:
    _CURRENT_SCOPE.reset(token)


def _set_context(
    context: RequestContext,
) -> contextvars.Token[RequestContext | None]:
    return _CURRENT_CONTEXT.set(context)


def _reset_context(token: contextvars.Token[RequestContext | None]) -> None:
    _CURRENT_CONTEXT.reset(token)


def _module_label(module_id: ModuleId) -> str:
    label = module_id.module.__qualname__
    return label if module_id.key is None else f"{label}[{module_id.key}]"


__all__ = [
    "RequestContext",
    "current_request_context",
    "current_request_scope",
]
