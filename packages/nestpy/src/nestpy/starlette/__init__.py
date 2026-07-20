"""Starlette HTTP driver for Nestpy applications."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nestpy.starlette.application import (
        ASGIApplication,
        StarletteAdapter,
        asgi,
    )
    from nestpy.starlette.context import (
        RequestContext,
        current_request_context,
    )
    from nestpy.starlette.options import StarletteOptions

__all__ = [
    "ASGIApplication",
    "RequestContext",
    "StarletteAdapter",
    "StarletteOptions",
    "asgi",
    "current_request_context",
]


def __getattr__(name: str) -> Any:
    if name in {"ASGIApplication", "StarletteAdapter", "asgi"}:
        from nestpy.starlette import application

        return getattr(application, name)
    if name == "StarletteOptions":
        from nestpy.starlette.options import StarletteOptions

        return StarletteOptions
    if name in {"RequestContext", "current_request_context"}:
        from nestpy.starlette import context

        return getattr(context, name)
    raise AttributeError(name)
