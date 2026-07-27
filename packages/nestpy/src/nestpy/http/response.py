"""Transport-neutral explicit HTTP response values and route metadata."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from nestpy.core.errors import BootstrapError

_HEADER_NAME_CHARACTERS = frozenset(
    "!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
)
_TRANSPORT_HEADERS = frozenset({"content-length", "transfer-encoding"})
_TOKEN = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+"
_MEDIA_TYPE = re.compile(
    rf'{_TOKEN}/{_TOKEN}(?:[ \t]*;[ \t]*{_TOKEN}=(?:{_TOKEN}|"(?:[^"\\]|\\.)*"))*'
)


def _empty_headers() -> Mapping[str, str]:
    return MappingProxyType({})


def _validate_header(name: object, value: object) -> tuple[str, str]:
    if (
        not isinstance(name, str)
        or not name
        or any(character not in _HEADER_NAME_CHARACTERS for character in name)
    ):
        raise ValueError("HttpResponse header names must be HTTP tokens")
    if not isinstance(value, str):
        raise TypeError("HttpResponse header values must be strings")
    if value.startswith((" ", "\t")) or value.endswith((" ", "\t")):
        raise ValueError(
            "HttpResponse header values must not have surrounding whitespace"
        )
    if "\r" in value or "\n" in value:
        raise ValueError("HttpResponse header values must not contain CR or LF")
    if any(
        (ord(character) < 32 and character != "\t") or ord(character) == 127
        for character in value
    ):
        raise ValueError(
            "HttpResponse header values must not contain control characters"
        )
    try:
        value.encode("latin-1")
    except UnicodeEncodeError as error:
        raise ValueError(
            "HttpResponse header values must be Latin-1 encodable"
        ) from error
    if name.casefold() == "content-type" and _MEDIA_TYPE.fullmatch(value) is None:
        raise ValueError("HttpResponse Content-Type must be a valid media type")
    return name, value


@dataclass(frozen=True, slots=True)
class ResponseHeaderMetadata:
    """One static response header attached to a route method."""

    name: str
    value: str

    def __post_init__(self) -> None:
        _validate_header(self.name, self.value)
        if self.name.casefold() in _TRANSPORT_HEADERS:
            raise ValueError("HttpResponse framing headers are transport-owned")


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Portable pre-encoded response content, status, and headers."""

    content: bytes
    status_code: int = 200
    headers: Mapping[str, str] = field(default_factory=_empty_headers)

    def __post_init__(self) -> None:
        if not isinstance(self.content, bytes):
            raise TypeError("HttpResponse content must be bytes")
        if type(self.status_code) is not int or not 200 <= self.status_code <= 599:
            raise ValueError("HttpResponse status_code must be between 200 and 599")
        if self.status_code in {204, 304} and self.content:
            raise ValueError("HttpResponse status 204 or 304 must not contain content")
        if not isinstance(self.headers, Mapping):
            raise TypeError("HttpResponse headers must be a mapping")
        copied = dict(self.headers)
        normalized_names: set[str] = set()
        for name, value in copied.items():
            name, _ = _validate_header(name, value)
            normalized_name = name.casefold()
            if normalized_name in normalized_names:
                raise ValueError("HttpResponse header names must be unique")
            if normalized_name in _TRANSPORT_HEADERS:
                raise ValueError("HttpResponse framing headers are transport-owned")
            normalized_names.add(normalized_name)
        object.__setattr__(self, "headers", MappingProxyType(copied))


def header(name: str, value: str) -> Any:
    """Attach one static header to a Nestpy-encoded route response."""

    try:
        metadata = ResponseHeaderMetadata(name, value)
    except (TypeError, ValueError) as error:
        raise BootstrapError(str(error), code="route.invalid_signature") from error

    def decorate(target: Any) -> Any:
        if isinstance(target, type) or not callable(target):
            raise BootstrapError(
                "header decorator target must be callable",
                code="route.invalid_signature",
            )
        existing = get_response_header_metadata(target)
        if any(item.name.casefold() == metadata.name.casefold() for item in existing):
            raise BootstrapError(
                f"response header {metadata.name!r} is already declared",
                code="route.invalid_signature",
            )
        target.__nestpy_response_header_metadata__ = (*existing, metadata)
        return target

    return decorate


def get_response_header_metadata(target: Any) -> tuple[ResponseHeaderMetadata, ...]:
    """Read static response headers attached directly to one route method."""

    metadata = getattr(target, "__dict__", {}).get(
        "__nestpy_response_header_metadata__", ()
    )
    if not isinstance(metadata, tuple) or any(
        not isinstance(item, ResponseHeaderMetadata) for item in metadata
    ):
        return ()
    return metadata


__all__ = [
    "HttpResponse",
    "ResponseHeaderMetadata",
    "get_response_header_metadata",
    "header",
]
