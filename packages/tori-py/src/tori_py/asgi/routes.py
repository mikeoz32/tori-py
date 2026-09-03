"""Compile and execute HTTP routes without a third-party ASGI framework."""

from __future__ import annotations

import asyncio
import dis
import inspect
import json
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from functools import wraps
from typing import cast

import msgspec

from tori_py.asgi.context import (
    RequestContext,
    _AsgiRequest,
    current_request_context,
)
from tori_py.asgi.pipeline import ClientDisconnect
from tori_py.core.errors import BootstrapError
from tori_py.core.protocols import PipelineResult
from tori_py.core.runtime import RequestScope
from tori_py.http.endpoints import CompiledEndpoint
from tori_py.http.errors import HttpException
from tori_py.http.pipeline import PipelineExecutor
from tori_py.http.response import HttpResponse, ResponseHeaderMetadata
from tori_py.http.routes import ParameterPlan, RoutePlan


@dataclass(frozen=True, slots=True)
class RouteMatch:
    plan: RoutePlan | None
    path_params: Mapping[str, object]
    endpoint: CompiledEndpoint[HttpResponse] | None = None
    allowed_methods: tuple[str, ...] = ()
    redirect_path: str | None = None


@dataclass(frozen=True, slots=True)
class _CompiledRoute:
    endpoint: CompiledEndpoint[HttpResponse]
    pattern: re.Pattern[str]
    converters: Mapping[str, Callable[[str], object]]
    allowed_methods: tuple[str, ...]

    def match_path(self, path: str) -> Mapping[str, object] | None:
        matched = self.pattern.fullmatch(path)
        if matched is None:
            return None
        try:
            return {
                name: self.converters[name](value)
                for name, value in matched.groupdict().items()
            }
        except TypeError, ValueError:
            return None


class AsgiRouter:
    """Ordered route matcher preserving controller declaration precedence."""

    def __init__(
        self,
        endpoints: tuple[CompiledEndpoint[HttpResponse], ...],
    ) -> None:
        self.routes = tuple(_compile_route(endpoint) for endpoint in endpoints)

    def match(self, path: str, method: str) -> RouteMatch:
        allowed_methods: list[str] = []
        for route in self.routes:
            path_params = route.match_path(path)
            if path_params is None:
                continue
            if method in route.allowed_methods:
                return RouteMatch(route.endpoint.plan, path_params, route.endpoint)
            for allowed_method in route.allowed_methods:
                if allowed_method not in allowed_methods:
                    allowed_methods.append(allowed_method)
        if allowed_methods:
            return RouteMatch(None, {}, allowed_methods=tuple(allowed_methods))
        alternate = path[:-1] if path.endswith("/") else f"{path}/"
        if alternate:
            for route in self.routes:
                if (
                    method in route.allowed_methods
                    and route.match_path(alternate) is not None
                ):
                    return RouteMatch(None, {}, redirect_path=alternate)
        return RouteMatch(None, {})


def validate_context_bindings(plans: tuple[RoutePlan, ...]) -> None:
    """Ensure this adapter can supply every declared HTTP context type."""

    for plan in plans:
        for parameter in plan.parameters:
            if parameter.kind != "context":
                continue
            annotation = parameter.annotation
            if not isinstance(annotation, type) or not issubclass(
                RequestContext, annotation
            ):
                raise BootstrapError(
                    f"route context parameter {parameter.name} is not compatible "
                    "with native ASGI RequestContext",
                    code="route.invalid_binding",
                )


def monitor_bodyless_handlers(plans: tuple[RoutePlan, ...]) -> tuple[RoutePlan, ...]:
    """Start disconnect monitoring only when a bodyless handler is invoked."""

    monitored: list[RoutePlan] = []
    for plan in plans:
        consumes_body = plan.rejects_body or any(
            parameter.kind in {"body", "body_stream"} for parameter in plan.parameters
        )
        if consumes_body or not _handler_may_suspend(plan):
            monitored.append(plan)
            continue
        monitored.append(
            replace(
                plan,
                handler=_monitor_handler(plan.handler, plan.handler_is_async),
                handler_is_async=True,
            )
        )
    return tuple(monitored)


def _monitor_handler(
    handler: Callable[..., object],
    handler_is_async: bool,
) -> Callable[..., Awaitable[object]]:
    @wraps(handler)
    async def monitored_handler(**arguments: object) -> object:
        context = current_request_context()
        if context is not None:
            context.request.on_handler_start()
        try:
            result = handler(**arguments) if arguments else handler()
            if handler_is_async:
                return await cast(Awaitable[object], result)
            if inspect.isawaitable(result):
                return await result
            return result
        finally:
            if context is not None:
                context.request.on_handler_end()

    return monitored_handler


def _handler_may_suspend(plan: RoutePlan) -> bool:
    if not plan.handler_is_async:
        return True
    return any(
        instruction.opname in {"YIELD_FROM", "YIELD_VALUE"}
        for instruction in dis.get_instructions(plan.handler)
    )


def compile_endpoint(
    plan: RoutePlan,
    pipeline: PipelineExecutor,
    *,
    body_size_limit: int,
) -> CompiledEndpoint[HttpResponse]:
    uses_simple_binding = not plan.parameters and not plan.rejects_body
    uses_body_stream = any(
        parameter.kind == "body_stream" for parameter in plan.parameters
    )

    async def encode_result(result: object) -> HttpResponse:
        return _encode_pipeline_result(result, plan.status_code, plan.response_headers)

    async def run(
        context: RequestContext,
        request_scope: RequestScope,
        bind_arguments: Callable[[], Awaitable[dict[str, object]]],
        validate_result: Callable[[], Awaitable[None]] | None = None,
    ) -> HttpResponse:
        result = await pipeline.run(
            plan,
            context,
            request_scope,
            bind_arguments=bind_arguments,
            encode_result=encode_result,
            validate_result=validate_result,
        )
        if not isinstance(result, HttpResponse):
            raise HttpException(500, "Pipeline did not produce a response.")
        return result

    if uses_simple_binding:

        async def execute(
            request: _AsgiRequest,
            context: RequestContext,
            request_scope: RequestScope,
        ) -> HttpResponse:
            return await run(context, request_scope, _empty_arguments)

        return CompiledEndpoint(plan, execute)

    validation_factory = (
        _body_stream_validation if uses_body_stream else _no_result_validation
    )

    async def execute(
        request: _AsgiRequest,
        context: RequestContext,
        request_scope: RequestScope,
    ) -> HttpResponse:
        body_stream: _AsgiBodyStream | None = None

        def bind_body_stream(max_bytes: int) -> _AsgiBodyStream:
            nonlocal body_stream
            body_stream = _AsgiBodyStream(request, max_bytes)
            return body_stream

        async def bind_arguments() -> dict[str, object]:
            return await _bind_arguments(
                plan,
                request,
                context,
                body_size_limit=body_size_limit,
                bind_body_stream=bind_body_stream,
            )

        validate = validation_factory(lambda: body_stream)

        try:
            return await run(context, request_scope, bind_arguments, validate)
        finally:
            if body_stream is not None:
                await body_stream.aclose()

    return CompiledEndpoint(plan, execute)


_EMPTY_ARGUMENTS: dict[str, object] = {}


async def _empty_arguments() -> dict[str, object]:
    return _EMPTY_ARGUMENTS


def _body_stream_validation(
    body_stream: Callable[[], _AsgiBodyStream | None],
) -> Callable[[], Awaitable[None]]:
    async def validate_result() -> None:
        stream = body_stream()
        if stream is not None and not stream.complete:
            raise HttpException(400, "Request body stream was not fully consumed.")

    return validate_result


def _no_result_validation(
    body_stream: Callable[[], _AsgiBodyStream | None],
) -> None:
    del body_stream
    return None


async def _bind_arguments(
    plan: RoutePlan,
    request: _AsgiRequest,
    context: RequestContext,
    *,
    body_size_limit: int,
    bind_body_stream: Callable[[int], object],
) -> dict[str, object]:
    arguments: dict[str, object] = {}
    if plan.rejects_body:
        await _reject_request_body(request, body_size_limit)
    for parameter in plan.parameters:
        if parameter.kind == "inject":
            provider_ref = parameter.provider_ref
            if provider_ref is None:
                raise HttpException(500, "Route dependency was not compiled.")
            value = await context.scope.resolve_ref(provider_ref)
        elif parameter.kind == "context":
            value = context
        elif parameter.kind == "body":
            value = await _read_json_body(request, body_size_limit)
        elif parameter.kind == "body_stream":
            value = bind_body_stream(cast(int, parameter.max_bytes))
        else:
            value = _read_http_value(request, parameter)
        if value is _MISSING:
            if parameter.has_default:
                value = parameter.default
            else:
                raise HttpException(
                    400,
                    f"Missing required {parameter.kind} value '{parameter.name}'.",
                )
        arguments[parameter.name] = value
    return arguments


async def _reject_request_body(request: _AsgiRequest, limit: int) -> None:
    size = 0
    while True:
        message = await request.receive()
        if message["type"] == "http.disconnect":
            raise ClientDisconnect
        if message["type"] != "http.request":
            raise RuntimeError("unexpected ASGI request message")
        size += len(message.get("body", b""))
        if size > limit:
            raise HttpException(413, "Request body exceeds the configured limit.")
        if not message.get("more_body", False):
            break
    if size:
        raise HttpException(400, "Request body is not allowed.")


def _read_http_value(request: _AsgiRequest, parameter: ParameterPlan) -> object:
    source = cast(str, parameter.source)
    if parameter.kind == "path":
        return request.path_params.get(source, _MISSING)
    if parameter.kind == "query":
        return _collapse_values(request.query_values(source))
    if parameter.kind == "header":
        return _collapse_values(request.header_values(source))
    if parameter.kind == "cookie":
        return request.cookies.get(source, _MISSING)
    raise HttpException(500, "Unknown route binding kind.")


async def _read_json_body(request: _AsgiRequest, limit: int) -> object:
    from tori_py.asgi.context import _BODY_UNSET

    if request.body is not _BODY_UNSET:
        return request.body
    content_type = _collapse_values(request.header_values("content-type"))
    media_type = (
        ("" if content_type is _MISSING else str(content_type).split(";", 1)[0])
        .strip()
        .casefold()
    )
    if media_type != "application/json" and not media_type.endswith("+json"):
        raise HttpException(415, "Request body must use a JSON media type.")
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await request.receive()
        if message["type"] == "http.disconnect":
            raise ClientDisconnect
        if message["type"] != "http.request":
            raise RuntimeError("unexpected ASGI request message")
        chunk = bytes(message.get("body", b""))
        size += len(chunk)
        if size > limit:
            raise HttpException(413, "Request body exceeds the configured limit.")
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    try:
        request.body = json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HttpException(400, "Request body contains malformed JSON.") from error
    return request.body


class _AsgiBodyStream:
    def __init__(self, request: _AsgiRequest, max_bytes: int) -> None:
        self._request = request
        self._max_bytes = max_bytes
        self._claimed = False
        self._closed = False
        self._complete = False
        self._size = 0
        self._active_task: asyncio.Task[object] | None = None

    @property
    def complete(self) -> bool:
        return self._complete

    def __aiter__(self) -> AsyncIterator[bytes]:
        if self._closed:
            raise RuntimeError("request body stream is closed")
        if self._claimed:
            raise RuntimeError("request body stream may only be consumed once")
        self._claimed = True
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[bytes]:
        while not self._complete:
            if self._closed:
                raise RuntimeError("request body stream is closed")
            active_task = asyncio.current_task()
            if active_task is None:
                raise RuntimeError("request body streaming requires an asyncio task")
            self._active_task = active_task
            try:
                message = await self._request.receive()
                if self._closed:
                    raise RuntimeError("request body stream is closed")
            finally:
                if self._active_task is active_task:
                    self._active_task = None
            if message["type"] == "http.disconnect":
                raise ClientDisconnect
            if message["type"] != "http.request":
                raise RuntimeError("unexpected ASGI request message")
            chunk = bytes(message.get("body", b""))
            self._size += len(chunk)
            if self._size > self._max_bytes:
                raise HttpException(413, "Request body exceeds the route limit.")
            self._complete = not message.get("more_body", False)
            if chunk:
                yield chunk

    async def aclose(self) -> None:
        self._closed = True
        active_task = self._active_task
        if active_task is None or active_task is asyncio.current_task():
            return
        if not active_task.done() and active_task.cancelling() == 0:
            active_task.cancel("request body stream closed")
        await asyncio.gather(active_task, return_exceptions=True)


def _encode_pipeline_result(
    result: object,
    status_code: int,
    response_headers: tuple[ResponseHeaderMetadata, ...] = (),
) -> HttpResponse:
    if isinstance(result, PipelineResult):
        if result.is_response and not isinstance(result.value, HttpResponse):
            raise HttpException(500, "Pipeline response is not an HTTP response.")
        result = result.value
    if isinstance(result, HttpResponse):
        return result
    try:
        content = msgspec.json.encode(result)
    except (TypeError, ValueError) as error:
        raise HttpException(
            500, "Handler result could not be encoded as JSON."
        ) from error
    headers = {
        header.name: header.value
        for header in response_headers
        if header.name.casefold() != "x-request-id"
    }
    headers["content-type"] = "application/json"
    return HttpResponse(content, status_code=status_code, headers=headers)


def _compile_route(endpoint: CompiledEndpoint[HttpResponse]) -> _CompiledRoute:
    plan = endpoint.plan
    converters: dict[str, Callable[[str], object]] = {}
    pattern_parts: list[str] = []
    position = 0
    for matched in _PARAMETER.finditer(plan.path):
        literal = plan.path[position : matched.start()]
        if "{" in literal or "}" in literal:
            _invalid_path(plan.path)
        pattern_parts.append(re.escape(literal))
        name = matched.group("name")
        converter_name = matched.group("converter") or "str"
        if name in converters or converter_name not in _CONVERTERS:
            _invalid_path(plan.path)
        expression, converter = _CONVERTERS[converter_name]
        pattern_parts.append(f"(?P<{name}>{expression})")
        converters[name] = converter
        position = matched.end()
    tail = plan.path[position:]
    if "{" in tail or "}" in tail:
        _invalid_path(plan.path)
    pattern_parts.append(re.escape(tail))
    allowed_methods = ("GET", "HEAD") if plan.method == "GET" else (plan.method,)
    return _CompiledRoute(
        endpoint,
        re.compile("".join(pattern_parts)),
        converters,
        allowed_methods,
    )


def _invalid_path(path: str) -> None:
    raise BootstrapError(
        "native ASGI route path is invalid",
        code="route.invalid_signature",
        details={"path": path},
    )


def _collapse_values(values: list[str]) -> object:
    if not values:
        return _MISSING
    return values[0] if len(values) == 1 else values


_PARAMETER = re.compile(
    r"{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::(?P<converter>[A-Za-z_][A-Za-z0-9_]*))?}"
)
_CONVERTERS: dict[str, tuple[str, Callable[[str], object]]] = {
    "str": (r"[^/]+", str),
    "path": (r".*", str),
    "int": (r"[0-9]+", int),
    "float": (r"[0-9]+(?:\.[0-9]+)?", float),
    "uuid": (
        r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}",
        uuid.UUID,
    ),
}
_MISSING = object()

__all__ = [
    "AsgiRouter",
    "RouteMatch",
    "monitor_bodyless_handlers",
    "validate_context_bindings",
]
