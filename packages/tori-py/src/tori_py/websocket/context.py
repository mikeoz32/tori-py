"""Transport-neutral WebSocket execution context and current-context storage."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from types import MappingProxyType

from tori_py.core.compiler import ModuleId
from tori_py.core.protocols import ScopedResolver
from tori_py.core.runtime import RequestScope


@dataclass(frozen=True, slots=True)
class WebSocketContext:
    """Connection execution metadata with an opaque native socket object."""

    socket: object
    scope: RequestScope
    module_identity: ModuleId
    application: str
    gateway: str
    connection_id_value: str

    @property
    def application_id(self) -> str:
        return self.application

    @property
    def module_id(self) -> str | None:
        label = self.module_identity.module.__qualname__
        if self.module_identity.key is None:
            return label
        return f"{label}[{self.module_identity.key}]"

    @property
    def route_id(self) -> str | None:
        return self.gateway

    @property
    def request_id(self) -> str | None:
        return self.connection_id_value

    @property
    def resolver(self) -> ScopedResolver:
        return self.scope.resolver_for(self.module_identity)

    @property
    def metadata(self) -> MappingProxyType[str, object]:
        return MappingProxyType({"socket": self.socket})

    @property
    def execution_kind(self) -> str:
        return "websocket"


_CURRENT_CONTEXT: contextvars.ContextVar[WebSocketContext | None] = (
    contextvars.ContextVar("tori_py_websocket_context", default=None)
)


def current_websocket_context() -> WebSocketContext | None:
    return _CURRENT_CONTEXT.get()


def _set_websocket_context(
    context: WebSocketContext,
) -> contextvars.Token[WebSocketContext | None]:
    return _CURRENT_CONTEXT.set(context)


def _reset_websocket_context(
    token: contextvars.Token[WebSocketContext | None],
) -> None:
    _CURRENT_CONTEXT.reset(token)


__all__ = ["WebSocketContext", "current_websocket_context"]
