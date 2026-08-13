"""Transport-independent expected HTTP failures."""

from collections.abc import Mapping


class HttpException(Exception):
    """An expected HTTP failure rendered by the selected HTTP adapter."""

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
        self.title = title or status_title(status_code)
        self.headers = dict(headers or {})
        self.errors = errors


def status_title(status_code: int) -> str:
    return {
        400: "Bad Request",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        413: "Payload Too Large",
        415: "Unsupported Media Type",
        500: "Internal Server Error",
        503: "Service Unavailable",
    }.get(status_code, "HTTP Error")


__all__ = ["HttpException"]
