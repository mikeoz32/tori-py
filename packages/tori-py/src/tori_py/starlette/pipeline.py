"""Starlette response and disconnect policy for the ToriPy HTTP executor."""

import logging
from typing import cast

from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response

from tori_py.core.protocols import PipelineResult
from tori_py.http._observability import log_http_emergency
from tori_py.http.context import HttpContext
from tori_py.http.errors import HttpException
from tori_py.starlette.errors import problem_response

logger = logging.getLogger("tori_py.starlette.pipeline")


class StarlettePipelineAdapter:
    """Bridge native Starlette responses into framework pipeline results."""

    def is_abort_exception(self, error: BaseException) -> bool:
        return isinstance(error, ClientDisconnect)

    def normalize_result(self, value: object) -> PipelineResult:
        if isinstance(value, PipelineResult):
            return value
        if isinstance(value, Response):
            return PipelineResult.from_response(value)
        return PipelineResult.from_value(value)

    def native_response_result(self, value: object) -> PipelineResult | None:
        return (
            PipelineResult.from_response(value) if isinstance(value, Response) else None
        )

    def render_exception(
        self,
        error: Exception,
        context: HttpContext,
    ) -> PipelineResult:
        request = cast(Request, context.request)
        if isinstance(error, HttpException):
            response = problem_response(
                error.status_code,
                error.detail,
                request=request,
                title=error.title,
                headers=error.headers,
                errors=error.errors,
            )
        else:
            log_http_emergency(
                logger,
                "tori_py.http.unhandled_exception",
            )
            response = problem_response(
                500,
                "Internal server error.",
                request=request,
            )
        return PipelineResult.from_response(response)

    def render_emergency(self, context: HttpContext) -> Response:
        return problem_response(
            500,
            "Internal server error.",
            request=cast(Request, context.request),
        )


__all__ = ["StarlettePipelineAdapter"]
