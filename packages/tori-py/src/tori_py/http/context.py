"""Framework-owned HTTP execution context and current-context storage."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from types import MappingProxyType

from tori_py.core.compiler import ModuleId
from tori_py.core.protocols import ScopedResolver
from tori_py.core.runtime import RequestScope


@dataclass(frozen=True, slots=True)
class HttpContext:
    """HTTP execution metadata with an opaque native request object."""

    request: object
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
        return MappingProxyType({"request": self.request})

    @property
    def execution_kind(self) -> str:
        return "http"


_CURRENT_CONTEXT: contextvars.ContextVar[HttpContext | None] = contextvars.ContextVar(
    "tori_py_http_context", default=None
)


def current_http_context() -> HttpContext | None:
    return _CURRENT_CONTEXT.get()


def current_request_scope() -> RequestScope | None:
    context = current_http_context()
    return None if context is None else context.scope


def _set_http_context(
    context: HttpContext | None,
) -> contextvars.Token[HttpContext | None]:
    return _CURRENT_CONTEXT.set(context)


def _reset_http_context(token: contextvars.Token[HttpContext | None]) -> None:
    _CURRENT_CONTEXT.reset(token)


def _module_label(module_id: ModuleId) -> str:
    label = module_id.module.__qualname__
    return label if module_id.key is None else f"{label}[{module_id.key}]"


__all__ = ["HttpContext", "current_http_context"]
