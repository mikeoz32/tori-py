"""Immutable declaration metadata for controllers and route methods."""

from dataclasses import dataclass
from typing import Any

from nestpy.core.errors import BootstrapError
from nestpy.core.providers import Token, validate_token


@dataclass(frozen=True, slots=True)
class ControllerMetadata:
    prefix: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.prefix, str):
            raise BootstrapError(
                "controller prefix must be a string",
                code="controller.invalid_declaration",
            )


@dataclass(frozen=True, slots=True)
class RouteMetadata:
    method: str
    path: str

    def __post_init__(self) -> None:
        if not self.method or not isinstance(self.method, str):
            raise BootstrapError(
                "route method must be a non-empty string",
                code="route.invalid_signature",
            )
        if not isinstance(self.path, str):
            raise BootstrapError(
                "route path must be a string",
                code="route.invalid_signature",
            )
        object.__setattr__(self, "method", self.method.upper())


@dataclass(frozen=True, slots=True)
class StatusMetadata:
    status_code: int

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise BootstrapError(
                "route status must be an HTTP status code",
                code="route.invalid_signature",
            )


@dataclass(frozen=True, slots=True)
class Body:
    """Bind one JSON request body without applying type conversion."""


@dataclass(frozen=True, slots=True)
class Path:
    """Bind one raw path value by its explicit source name."""

    name: str

    def __post_init__(self) -> None:
        _validate_binding_name(self.name, "path")


@dataclass(frozen=True, slots=True)
class Query:
    """Bind one raw query value by its explicit source name."""

    name: str

    def __post_init__(self) -> None:
        _validate_binding_name(self.name, "query")


@dataclass(frozen=True, slots=True)
class Header:
    """Bind one raw header value by its explicit source name."""

    name: str

    def __post_init__(self) -> None:
        _validate_binding_name(self.name, "header")


@dataclass(frozen=True, slots=True)
class Cookie:
    """Bind one raw cookie value by its explicit source name."""

    name: str

    def __post_init__(self) -> None:
        _validate_binding_name(self.name, "cookie")


@dataclass(frozen=True, slots=True)
class Context:
    """Bind the driver-neutral request execution context."""


_PIPELINE_ATTRIBUTES = {
    "middleware": "__nestpy_middleware_metadata__",
    "guards": "__nestpy_guards_metadata__",
    "pipes": "__nestpy_pipes_metadata__",
    "interceptors": "__nestpy_interceptors_metadata__",
    "filters": "__nestpy_filters_metadata__",
}


def _pipeline_decorator(kind: str, tokens: tuple[Token, ...]) -> Any:
    attribute = _PIPELINE_ATTRIBUTES[kind]
    normalized = tuple(validate_token(token) for token in tokens)

    def decorate(target: Any) -> Any:
        return _attach(
            target,
            attribute,
            normalized,
            "route.duplicate_pipeline_decorator",
        )

    return decorate


def use_middleware(*tokens: Token) -> Any:
    return _pipeline_decorator("middleware", tokens)


def use_guards(*tokens: Token) -> Any:
    return _pipeline_decorator("guards", tokens)


def use_pipes(*tokens: Token) -> Any:
    return _pipeline_decorator("pipes", tokens)


def use_interceptors(*tokens: Token) -> Any:
    return _pipeline_decorator("interceptors", tokens)


def use_filters(*tokens: Token) -> Any:
    return _pipeline_decorator("filters", tokens)


middleware = use_middleware
guards = use_guards
pipes = use_pipes
interceptors = use_interceptors
filters = use_filters


def get_pipeline_metadata(target: Any, kind: str) -> tuple[Token, ...]:
    attribute = _PIPELINE_ATTRIBUTES[kind]
    value = getattr(target, attribute, ())
    return value if isinstance(value, tuple) else ()


def _validate_binding_name(name: str, kind: str) -> None:
    if not isinstance(name, str) or not name:
        raise BootstrapError(
            f"{kind} binding source name must be non-empty",
            code="route.invalid_binding",
        )


def _attach(target: Any, attribute: str, metadata: object, code: str) -> Any:
    if attribute in getattr(target, "__dict__", {}):
        raise BootstrapError(
            f"{attribute} is already declared on this target",
            code=code,
        )
    setattr(target, attribute, metadata)
    return target


def controller(prefix: str = "") -> Any:
    """Attach controller metadata directly to a class."""

    metadata = ControllerMetadata(prefix)

    def decorate(target: type[object]) -> type[object]:
        return _attach(
            target,
            "__nestpy_controller_metadata__",
            metadata,
            "controller.duplicate_metadata",
        )

    return decorate


def route(method: str, path: str = "") -> Any:
    """Attach one route declaration to a method without creating a router."""

    metadata = RouteMetadata(method, path)

    def decorate(target: Any) -> Any:
        return _attach(
            target,
            "__nestpy_route_metadata__",
            metadata,
            "route.duplicate_metadata",
        )

    return decorate


def status(status_code: int) -> Any:
    """Attach an encoded-response status to a route method."""

    metadata = StatusMetadata(status_code)

    def decorate(target: Any) -> Any:
        return _attach(
            target,
            "__nestpy_status_metadata__",
            metadata,
            "route.duplicate_metadata",
        )

    return decorate


def get(path: str = "") -> Any:
    return route("GET", path)


def post(path: str = "") -> Any:
    return route("POST", path)


def put(path: str = "") -> Any:
    return route("PUT", path)


def patch(path: str = "") -> Any:
    return route("PATCH", path)


def delete(path: str = "") -> Any:
    return route("DELETE", path)


def options(path: str = "") -> Any:
    return route("OPTIONS", path)


def head(path: str = "") -> Any:
    return route("HEAD", path)


def get_controller_metadata(target: type[object]) -> ControllerMetadata | None:
    metadata = target.__dict__.get("__nestpy_controller_metadata__")
    return metadata if isinstance(metadata, ControllerMetadata) else None


def get_route_metadata(target: Any) -> RouteMetadata | None:
    metadata = getattr(target, "__nestpy_route_metadata__", None)
    return metadata if isinstance(metadata, RouteMetadata) else None


def get_status_metadata(target: Any) -> StatusMetadata | None:
    metadata = getattr(target, "__nestpy_status_metadata__", None)
    return metadata if isinstance(metadata, StatusMetadata) else None


__all__ = [
    "Body",
    "Context",
    "Cookie",
    "ControllerMetadata",
    "filters",
    "get_pipeline_metadata",
    "guards",
    "Header",
    "interceptors",
    "middleware",
    "Path",
    "pipes",
    "Query",
    "RouteMetadata",
    "StatusMetadata",
    "controller",
    "delete",
    "get",
    "get_controller_metadata",
    "get_route_metadata",
    "get_status_metadata",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "route",
    "status",
    "use_filters",
    "use_guards",
    "use_interceptors",
    "use_middleware",
    "use_pipes",
]
