"""HTTP exception and RFC 9457 problem response helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping

from starlette.requests import Request
from starlette.responses import Response


class HttpException(Exception):
    """An expected HTTP failure rendered as Problem Details."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        title: str | None = None,
        headers: Mapping[str, str] | None = None,
        errors: object | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.title = title or _status_title(status_code)
        self.headers = dict(headers or {})
        self.errors = errors


def problem_response(
    status_code: int,
    detail: str,
    *,
    request: Request | None = None,
    title: str | None = None,
    headers: Mapping[str, str] | None = None,
    errors: object | None = None,
) -> Response:
    body = {
        "type": "about:blank",
        "title": title or _status_title(status_code),
        "status": status_code,
        "detail": detail,
    }
    if request is not None:
        request_id = request.scope.get("nestpy_request_id")
        if isinstance(request_id, str):
            body["instance"] = request.url.path
    if errors is not None:
        body["errors"] = errors
    response_headers: dict[str, str] = {}
    for key, value in (headers or {}).items():
        if key.casefold() not in {"content-type", "x-request-id"}:
            response_headers[key] = value
    response_headers["content-type"] = "application/problem+json"
    if request is not None:
        request_id = request.scope.get("nestpy_request_id")
        if isinstance(request_id, str):
            response_headers["X-Request-ID"] = request_id
    return Response(
        json.dumps(body, separators=(",", ":")),
        status_code=status_code,
        headers=response_headers,
        media_type=None,
    )


async def http_exception_handler(request: Request, error: HttpException) -> Response:
    return problem_response(
        error.status_code,
        error.detail,
        request=request,
        title=error.title,
        headers=error.headers,
        errors=error.errors,
    )


async def not_found_handler(request: Request, _error: Exception) -> Response:
    return problem_response(
        404, "The requested resource was not found.", request=request
    )


async def method_not_allowed_handler(
    request: Request,
    _error: Exception,
) -> Response:
    return problem_response(405, "The HTTP method is not allowed.", request=request)


async def server_error_handler(request: Request, _error: Exception) -> Response:
    return problem_response(500, "Internal server error.", request=request)


def _status_title(status_code: int) -> str:
    return {
        400: "Bad Request",
        404: "Not Found",
        405: "Method Not Allowed",
        403: "Forbidden",
        413: "Payload Too Large",
        415: "Unsupported Media Type",
        500: "Internal Server Error",
        503: "Service Unavailable",
    }.get(status_code, "HTTP Error")


__all__ = ["HttpException", "problem_response"]
