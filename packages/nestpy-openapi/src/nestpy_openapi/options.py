"""Immutable OpenAPI and Swagger UI configuration."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, cast
from urllib.parse import SplitResult, urlsplit

import msgspec

from nestpy_openapi.errors import OpenApiConfigurationError

_COMPONENT_NAME_PATTERN = r"^[a-zA-Z0-9._-]+$"
_COMPONENT_NAME_CHARACTERS: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)
_RESERVED_SWAGGER_PARAMETERS: Final[frozenset[str]] = frozenset(
    {"dom_id", "spec", "url", "urls"}
)
_SWAGGER_UI_VERSION = "5.31.0"
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_DEFAULT_JAVASCRIPT_URL = (
    f"https://unpkg.com/swagger-ui-dist@{_SWAGGER_UI_VERSION}/swagger-ui-bundle.js"
)
_DEFAULT_STYLESHEET_URL = (
    f"https://unpkg.com/swagger-ui-dist@{_SWAGGER_UI_VERSION}/swagger-ui.css"
)


def _empty_mapping() -> Mapping[str, object]:
    return MappingProxyType({})


def _require_string(value: object, name: str, *, non_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise OpenApiConfigurationError(f"{name} must be a string")
    if non_empty and not value.strip():
        raise OpenApiConfigurationError(f"{name} must not be empty")
    return value


def _optional_string(value: object, name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise OpenApiConfigurationError(f"{name} must be a string or None")


def _validate_parsed_port(parsed: SplitResult) -> None:
    port = parsed.port
    # urlsplit currently rejects this before returning the port.
    if port is not None and not 0 <= port <= 65535:  # pragma: no cover
        raise ValueError("URL port is out of range")


def _validate_endpoint_path(value: object, name: str) -> str:
    path = _require_string(value, name, non_empty=True)
    if (
        not path.startswith("/")
        or path.startswith("//")
        or "?" in path
        or "#" in path
        or "{" in path
        or "}" in path
        or "\\" in path
        or any(character.isspace() or ord(character) < 32 for character in path)
    ):
        raise OpenApiConfigurationError(
            f"{name} must be an absolute static path without a query or fragment"
        )
    return path


def _validate_asset_url(value: object, name: str) -> str:
    url = _require_string(value, name, non_empty=True)
    if (
        "\\" in url
        or _INVALID_PERCENT_ESCAPE.search(url)
        or any(character.isspace() or ord(character) < 32 for character in url)
    ):
        raise OpenApiConfigurationError(
            f"{name} must be an absolute HTTPS URL or root-relative path"
        )
    try:
        parsed = urlsplit(url)
        is_https = (
            parsed.scheme == "https"
            and bool(parsed.netloc)
            and parsed.hostname is not None
        )
        if is_https:
            _validate_parsed_port(parsed)
        is_root_relative = (
            not parsed.scheme
            and not parsed.netloc
            and parsed.path.startswith("/")
            and not parsed.path.startswith("//")
        )
    except ValueError as error:
        raise OpenApiConfigurationError(f"{name} is not a valid asset URL") from error
    if not is_https and not is_root_relative:
        raise OpenApiConfigurationError(
            f"{name} must be an absolute HTTPS URL or root-relative path"
        )
    return url


def _validate_server_url(value: object) -> str:
    url = _require_string(value, "server url", non_empty=True)
    if (
        "\\" in url
        or "{" in url
        or "}" in url
        or _INVALID_PERCENT_ESCAPE.search(url)
        or any(character.isspace() or ord(character) < 32 for character in url)
    ):
        raise OpenApiConfigurationError(
            "server url contains unsupported or invalid URL characters"
        )
    try:
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc:
            if not parsed.netloc or parsed.hostname is None:
                raise ValueError("absolute server URL requires a host")
            _validate_parsed_port(parsed)
        elif ":" in parsed.path.partition("/")[0]:
            raise ValueError("relative server URL has a colon in its first segment")
    except ValueError as error:
        raise OpenApiConfigurationError("server url is not a valid URL") from error
    return url


def _freeze_json(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _freeze_parameters(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise OpenApiConfigurationError("parameters must be a mapping")
    copied = dict(value)
    if any(not isinstance(key, str) for key in copied):
        raise OpenApiConfigurationError("parameters keys must be strings")
    reserved = _RESERVED_SWAGGER_PARAMETERS.intersection(copied)
    if reserved:
        key = sorted(reserved)[0]
        raise OpenApiConfigurationError(f"Swagger UI parameter {key!r} is reserved")
    try:
        normalized = msgspec.json.decode(msgspec.json.encode(copied))
    except (TypeError, ValueError, RecursionError) as error:
        raise OpenApiConfigurationError(
            "Swagger UI parameter values must be JSON encodable"
        ) from error
    if not isinstance(normalized, dict):  # pragma: no cover - encoded from a dict
        raise OpenApiConfigurationError("parameters must encode as a JSON object")
    frozen = _freeze_json(normalized)
    if not isinstance(frozen, Mapping):  # pragma: no cover - frozen from a dict
        raise OpenApiConfigurationError("parameters must encode as a JSON object")
    return cast(Mapping[str, object], frozen)


def _freeze_options[T](
    value: object,
    *,
    name: str,
    option_type: type[T],
) -> tuple[T, ...]:
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise OpenApiConfigurationError(f"{name} must be an iterable")
    copied = tuple(value)
    if any(not isinstance(item, option_type) for item in copied):
        raise OpenApiConfigurationError(
            f"{name} values must be {option_type.__name__} instances"
        )
    return cast(tuple[T, ...], copied)


@dataclass(frozen=True, slots=True)
class OpenApiInfo:
    """Required root information for the generated OpenAPI document."""

    title: str
    version: str
    description: str | None = None

    def __post_init__(self) -> None:
        _require_string(self.title, "info title", non_empty=True)
        _require_string(self.version, "info version", non_empty=True)
        _optional_string(self.description, "info description")


@dataclass(frozen=True, slots=True)
class OpenApiServer:
    """One server advertised by the generated OpenAPI document."""

    url: str
    description: str | None = None

    def __post_init__(self) -> None:
        _validate_server_url(self.url)
        _optional_string(self.description, "server description")


@dataclass(frozen=True, slots=True)
class BearerSecurityScheme:
    """A named HTTP bearer security scheme."""

    name: str
    bearer_format: str | None = "JWT"
    description: str | None = None

    def __post_init__(self) -> None:
        name = _require_string(self.name, "security scheme name", non_empty=True)
        if any(character not in _COMPONENT_NAME_CHARACTERS for character in name):
            raise OpenApiConfigurationError(
                "security scheme name must match " + _COMPONENT_NAME_PATTERN
            )
        _optional_string(self.bearer_format, "bearer format")
        _optional_string(self.description, "security scheme description")


@dataclass(frozen=True, slots=True)
class SwaggerUiOptions:
    """Pinned Swagger UI assets and immutable client parameters."""

    javascript_url: str = _DEFAULT_JAVASCRIPT_URL
    stylesheet_url: str = _DEFAULT_STYLESHEET_URL
    parameters: Mapping[str, object] = field(default_factory=_empty_mapping)

    def __post_init__(self) -> None:
        _validate_asset_url(self.javascript_url, "Swagger UI javascript_url")
        _validate_asset_url(self.stylesheet_url, "Swagger UI stylesheet_url")
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))


@dataclass(frozen=True, slots=True)
class OpenApiOptions:
    """Complete setup configuration for one compiled Nestpy application."""

    info: OpenApiInfo
    docs_path: str | None = "/docs"
    openapi_path: str = "/openapi.json"
    servers: tuple[OpenApiServer, ...] = ()
    security_schemes: tuple[BearerSecurityScheme, ...] = ()
    swagger_ui: SwaggerUiOptions = SwaggerUiOptions()

    def __post_init__(self) -> None:
        if not isinstance(self.info, OpenApiInfo):
            raise OpenApiConfigurationError("info must be an OpenApiInfo instance")
        if self.docs_path is not None:
            _validate_endpoint_path(self.docs_path, "docs_path")
        _validate_endpoint_path(self.openapi_path, "openapi_path")
        if self.docs_path == self.openapi_path:
            raise OpenApiConfigurationError(
                "docs_path and openapi_path must be distinct"
            )
        servers = _freeze_options(
            self.servers,
            name="servers",
            option_type=OpenApiServer,
        )
        security_schemes = _freeze_options(
            self.security_schemes,
            name="security_schemes",
            option_type=BearerSecurityScheme,
        )
        names = [scheme.name for scheme in security_schemes]
        if len(names) != len(set(names)):
            raise OpenApiConfigurationError("security scheme names must be unique")
        if not isinstance(self.swagger_ui, SwaggerUiOptions):
            raise OpenApiConfigurationError(
                "swagger_ui must be a SwaggerUiOptions instance"
            )
        object.__setattr__(self, "servers", servers)
        object.__setattr__(self, "security_schemes", security_schemes)


__all__ = [
    "BearerSecurityScheme",
    "OpenApiInfo",
    "OpenApiOptions",
    "OpenApiServer",
    "SwaggerUiOptions",
]
