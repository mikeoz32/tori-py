"""Render framework HTTP errors as native Starlette responses."""

from __future__ import annotations

import json
from collections.abc import Mapping

from starlette.requests import Request
from starlette.responses import Response

from nestpy.http.errors import status_title


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
        "title": title or status_title(status_code),
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


__all__ = ["problem_response"]
