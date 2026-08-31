"""Starlette HTTP and WebSocket driver for ToriPy applications."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tori_py.starlette.application import (
        ASGIApplication,
        StarletteAdapter,
        asgi,
    )
    from tori_py.starlette.context import (
        RequestContext,
        current_request_context,
    )
    from tori_py.starlette.options import StarletteOptions
    from tori_py.starlette.websockets import WebSocketRequestContext

__all__ = [
    "ASGIApplication",
    "RequestContext",
    "StarletteAdapter",
    "StarletteOptions",
    "WebSocketRequestContext",
    "asgi",
    "current_request_context",
]


def __getattr__(name: str) -> Any:
    if name in {"ASGIApplication", "StarletteAdapter", "asgi"}:
        from tori_py.starlette import application

        return getattr(application, name)
    if name == "StarletteOptions":
        from tori_py.starlette.options import StarletteOptions

        return StarletteOptions
    if name in {"RequestContext", "current_request_context"}:
        from tori_py.starlette import context

        return getattr(context, name)
    if name == "WebSocketRequestContext":
        from tori_py.starlette.websockets import WebSocketRequestContext

        return WebSocketRequestContext
    raise AttributeError(name)
