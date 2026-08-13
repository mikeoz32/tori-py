"""Starlette HTTP driver for ToriPy applications."""

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
        from tori_py.starlette import application

        return getattr(application, name)
    if name == "StarletteOptions":
        from tori_py.starlette.options import StarletteOptions

        return StarletteOptions
    if name in {"RequestContext", "current_request_context"}:
        from tori_py.starlette import context

        return getattr(context, name)
    raise AttributeError(name)
