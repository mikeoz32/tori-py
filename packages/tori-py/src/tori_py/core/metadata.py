"""Immutable declaration metadata for controllers and route methods."""

import inspect
from dataclasses import dataclass
from typing import Any

from tori_py.core.errors import BootstrapError
from tori_py.core.protocols import (
    ExceptionFilter,
    Guard,
    Interceptor,
    MethodInterceptor,
    Pipe,
)
from tori_py.core.providers import Token, validate_token


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
class NoBodyMetadata:
    """Require an empty request body after guards complete."""


@dataclass(frozen=True, slots=True)
class Body:
    """Bind one JSON request body without applying type conversion."""


@dataclass(frozen=True, slots=True)
class BodyStream:
    """Bind one raw request-body byte stream with a route-specific limit."""

    max_bytes: int

    def __post_init__(self) -> None:
        if type(self.max_bytes) is not int or self.max_bytes < 0:
            raise BootstrapError(
                "body stream max_bytes must be a non-negative integer",
                code="route.invalid_binding",
            )


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


@dataclass(frozen=True, slots=True)
class Socket:
    """Bind the adapter-native WebSocket connection."""


@dataclass(frozen=True, slots=True)
class WebSocketGatewayMetadata:
    path: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str):
            raise BootstrapError(
                "WebSocket gateway path must be a string",
                code="gateway.invalid_declaration",
            )


_PIPELINE_ATTRIBUTES = {
    "middleware": "__tori_py_middleware_metadata__",
    "guards": "__tori_py_guards_metadata__",
    "pipes": "__tori_py_pipes_metadata__",
    "interceptors": "__tori_py_interceptors_metadata__",
    "filters": "__tori_py_filters_metadata__",
}
_PIPELINE_METHODS = {
    "guards": "can_activate",
    "pipes": "transform",
    "interceptors": "intercept",
    "filters": "catch",
}
_METHOD_INTERCEPTORS_ATTRIBUTE = "__tori_py_method_interceptors_metadata__"

type GuardBinding = Token | Guard
type PipeBinding = Token | Pipe
type InterceptorBinding = Token | Interceptor
type FilterBinding = Token | ExceptionFilter
type PipelineBinding = GuardBinding | PipeBinding | InterceptorBinding | FilterBinding
type MethodInterceptorBinding = Token | MethodInterceptor


def validate_pipeline_binding(kind: str, binding: object) -> object:
    """Validate a provider token or direct enhancer instance."""

    if isinstance(binding, str | type):
        return validate_token(binding)
    method_name = _PIPELINE_METHODS.get(kind)
    if method_name is not None and callable(getattr(binding, method_name, None)):
        return binding
    if method_name is None:
        message = f"{kind} registration must be a provider token"
    else:
        message = (
            f"{kind} registration must be a provider token or {method_name} instance"
        )
    raise BootstrapError(
        message,
        code="route.invalid_signature",
    )


def validate_method_interceptor_binding(binding: object) -> MethodInterceptorBinding:
    """Validate one method-interceptor provider token or direct instance."""

    if isinstance(binding, str | type):
        return validate_token(binding)
    if isinstance(binding, MethodInterceptor) and inspect.iscoroutinefunction(
        binding.intercept
    ):
        return binding
    raise BootstrapError(
        "method interceptor registration must be a provider token or "
        "MethodInterceptor instance",
        code="provider.invalid_declaration",
    )


def use_method_interceptors(*interceptors: MethodInterceptorBinding) -> Any:
    """Attach method interceptors; stacked decorators preserve outer-first order."""

    if not interceptors:
        raise BootstrapError(
            "method interceptor registration must not be empty",
            code="provider.invalid_declaration",
        )
    normalized = tuple(
        validate_method_interceptor_binding(interceptor) for interceptor in interceptors
    )

    def decorate(target: Any) -> Any:
        metadata_target = (
            target.__func__
            if isinstance(target, classmethod | staticmethod)
            else target
        )
        own = getattr(metadata_target, "__dict__", {})
        existing = own.get(_METHOD_INTERCEPTORS_ATTRIBUTE, ())
        if not isinstance(existing, tuple):
            existing = ()
        setattr(
            metadata_target,
            _METHOD_INTERCEPTORS_ATTRIBUTE,
            normalized + existing,
        )
        return target

    return decorate


def use_method_interceptor(interceptor: MethodInterceptorBinding) -> Any:
    """Attach one method interceptor."""

    return use_method_interceptors(interceptor)


def get_method_interceptors(target: Any) -> tuple[MethodInterceptorBinding, ...]:
    """Return method interceptors directly attached to a method."""

    metadata_target = (
        target.__func__ if isinstance(target, classmethod | staticmethod) else target
    )
    value = getattr(metadata_target, "__dict__", {}).get(
        _METHOD_INTERCEPTORS_ATTRIBUTE,
        (),
    )
    return value if isinstance(value, tuple) else ()


def _pipeline_decorator(kind: str, bindings: tuple[object, ...]) -> Any:
    attribute = _PIPELINE_ATTRIBUTES[kind]
    normalized = tuple(validate_pipeline_binding(kind, binding) for binding in bindings)

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


def use_guards(*guards: GuardBinding) -> Any:
    return _pipeline_decorator("guards", guards)


def use_guard(guard: GuardBinding) -> Any:
    return use_guards(guard)


def use_pipes(*pipes: PipeBinding) -> Any:
    return _pipeline_decorator("pipes", pipes)


def use_pipe(pipe: PipeBinding) -> Any:
    return use_pipes(pipe)


def use_interceptors(*interceptors: InterceptorBinding) -> Any:
    return _pipeline_decorator("interceptors", interceptors)


def use_interceptor(interceptor: InterceptorBinding) -> Any:
    return use_interceptors(interceptor)


def use_filters(*filters: FilterBinding) -> Any:
    return _pipeline_decorator("filters", filters)


def use_filter(filter_: FilterBinding) -> Any:
    return use_filters(filter_)


middleware = use_middleware
guards = use_guards
pipes = use_pipes
interceptors = use_interceptors
filters = use_filters


def get_pipeline_metadata(target: Any, kind: str) -> tuple[object, ...]:
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
            "__tori_py_controller_metadata__",
            metadata,
            "controller.duplicate_metadata",
        )

    return decorate


def websocket_gateway(path: str) -> Any:
    """Attach one native WebSocket connection path to a provider class."""

    metadata = WebSocketGatewayMetadata(path)

    def decorate(target: type[object]) -> type[object]:
        return _attach(
            target,
            "__tori_py_websocket_gateway_metadata__",
            metadata,
            "gateway.duplicate_metadata",
        )

    return decorate


def route(method: str, path: str = "") -> Any:
    """Attach one route declaration to a method without creating a router."""

    metadata = RouteMetadata(method, path)

    def decorate(target: Any) -> Any:
        return _attach(
            target,
            "__tori_py_route_metadata__",
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
            "__tori_py_status_metadata__",
            metadata,
            "route.duplicate_metadata",
        )

    return decorate


def no_body(target: Any) -> Any:
    """Reject non-empty request content before route argument binding."""

    return _attach(
        target,
        "__tori_py_no_body_metadata__",
        NoBodyMetadata(),
        "route.duplicate_metadata",
    )


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
    metadata = target.__dict__.get("__tori_py_controller_metadata__")
    return metadata if isinstance(metadata, ControllerMetadata) else None


def get_websocket_gateway_metadata(
    target: type[object],
) -> WebSocketGatewayMetadata | None:
    metadata = target.__dict__.get("__tori_py_websocket_gateway_metadata__")
    return metadata if isinstance(metadata, WebSocketGatewayMetadata) else None


def get_route_metadata(target: Any) -> RouteMetadata | None:
    metadata = getattr(target, "__tori_py_route_metadata__", None)
    return metadata if isinstance(metadata, RouteMetadata) else None


def get_status_metadata(target: Any) -> StatusMetadata | None:
    metadata = getattr(target, "__tori_py_status_metadata__", None)
    return metadata if isinstance(metadata, StatusMetadata) else None


def get_no_body_metadata(target: Any) -> NoBodyMetadata | None:
    metadata = getattr(target, "__tori_py_no_body_metadata__", None)
    return metadata if isinstance(metadata, NoBodyMetadata) else None


__all__ = [
    "Body",
    "BodyStream",
    "Context",
    "Cookie",
    "ControllerMetadata",
    "filters",
    "get_method_interceptors",
    "get_pipeline_metadata",
    "guards",
    "Header",
    "interceptors",
    "middleware",
    "NoBodyMetadata",
    "no_body",
    "Path",
    "pipes",
    "Query",
    "Socket",
    "RouteMetadata",
    "StatusMetadata",
    "WebSocketGatewayMetadata",
    "controller",
    "delete",
    "get",
    "get_controller_metadata",
    "get_no_body_metadata",
    "get_route_metadata",
    "get_status_metadata",
    "get_websocket_gateway_metadata",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "route",
    "status",
    "use_filters",
    "use_filter",
    "use_guard",
    "use_guards",
    "use_interceptor",
    "use_interceptors",
    "use_method_interceptor",
    "use_method_interceptors",
    "use_middleware",
    "use_pipe",
    "use_pipes",
    "websocket_gateway",
]
