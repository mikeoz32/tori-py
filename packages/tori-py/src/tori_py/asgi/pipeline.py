"""Native ASGI response and disconnect policy for the HTTP executor."""

import logging

from tori_py.asgi.errors import problem_response
from tori_py.core.protocols import PipelineResult
from tori_py.http._observability import log_http_emergency
from tori_py.http.context import HttpContext
from tori_py.http.errors import HttpException
from tori_py.http.response import HttpResponse

logger = logging.getLogger("tori_py.asgi.pipeline")


class ClientDisconnect(Exception):
    """The ASGI server reported that the HTTP client disconnected."""


class AsgiPipelineAdapter:
    """Bridge portable responses into framework pipeline results."""

    def is_abort_exception(self, error: BaseException) -> bool:
        return isinstance(error, (ClientDisconnect, OSError))

    def normalize_result(self, value: object) -> PipelineResult:
        if isinstance(value, PipelineResult):
            return value
        if isinstance(value, HttpResponse):
            return PipelineResult.from_response(value)
        return PipelineResult.from_value(value)

    def native_response_result(self, value: object) -> PipelineResult | None:
        return (
            PipelineResult.from_response(value)
            if isinstance(value, HttpResponse)
            else None
        )

    def render_exception(
        self,
        error: Exception,
        context: HttpContext,
    ) -> PipelineResult:
        if isinstance(error, HttpException):
            response = problem_response(
                error.status_code,
                error.detail,
                path=cast_path(context),
                title=error.title,
                headers=error.headers,
                errors=error.errors,
            )
        else:
            log_http_emergency(logger, "tori_py.http.unhandled_exception")
            response = problem_response(
                500,
                "Internal server error.",
                path=cast_path(context),
            )
        return PipelineResult.from_response(response)

    def render_emergency(self, context: HttpContext) -> HttpResponse:
        return problem_response(
            500,
            "Internal server error.",
            path=cast_path(context),
        )


def cast_path(context: HttpContext) -> str:
    path = getattr(context, "path", "/")
    return path if isinstance(path, str) else "/"


__all__ = ["AsgiPipelineAdapter", "ClientDisconnect"]
