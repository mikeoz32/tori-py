"""Starlette HTTP driver for Nestpy applications."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nestpy.starlette.application import (
        ASGIApplication,
        NestApplication,
        StarletteBinder,
        asgi,
    )
    from nestpy.starlette.context import (
        RequestContext,
        current_request_context,
        current_request_scope,
    )
    from nestpy.starlette.errors import HttpException
    from nestpy.starlette.pipeline import MsgspecValidationPipe, PipelineExecutor

__all__ = [
    "ASGIApplication",
    "HttpException",
    "MsgspecValidationPipe",
    "NestApplication",
    "PipelineExecutor",
    "RequestContext",
    "StarletteBinder",
    "asgi",
    "current_request_context",
    "current_request_scope",
]


def __getattr__(name: str) -> Any:
    if name in {"ASGIApplication", "NestApplication", "StarletteBinder", "asgi"}:
        from nestpy.starlette import application

        return getattr(application, name)
    if name in {"RequestContext", "current_request_context", "current_request_scope"}:
        from nestpy.starlette import context

        return getattr(context, name)
    if name == "HttpException":
        from nestpy.starlette.errors import HttpException

        return HttpException
    if name in {"MsgspecValidationPipe", "PipelineExecutor"}:
        from nestpy.starlette import pipeline

        return getattr(pipeline, name)
    raise AttributeError(name)
