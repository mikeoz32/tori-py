"""Render framework HTTP errors as portable ASGI response values."""

from __future__ import annotations

from collections.abc import Mapping

import msgspec

from tori_py.http.errors import status_title
from tori_py.http.response import HttpResponse


def problem_response(
    status_code: int,
    detail: str,
    *,
    path: str | None = None,
    title: str | None = None,
    headers: Mapping[str, str] | None = None,
    errors: object | None = None,
) -> HttpResponse:
    body: dict[str, object] = {
        "type": "about:blank",
        "title": title or status_title(status_code),
        "status": status_code,
        "detail": detail,
    }
    if path is not None:
        body["instance"] = path
    if errors is not None:
        body["errors"] = errors
    response_headers = {
        key: value
        for key, value in (headers or {}).items()
        if key.casefold() not in {"content-type", "x-request-id"}
    }
    response_headers["content-type"] = "application/problem+json"
    return HttpResponse(
        msgspec.json.encode(body),
        status_code=status_code,
        headers=response_headers,
    )


__all__ = ["problem_response"]
