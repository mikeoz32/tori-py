"""Register framework HTTP route plans with native Starlette routing."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import cast

import msgspec
from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response
from starlette.routing import Route

from tori_py.core.errors import BootstrapError
from tori_py.core.protocols import PipelineResult
from tori_py.core.providers import Token
from tori_py.http.context import current_request_scope
from tori_py.http.errors import HttpException
from tori_py.http.pipeline import PipelineExecutor
from tori_py.http.response import HttpResponse, ResponseHeaderMetadata
from tori_py.http.routes import ParameterPlan, RoutePlan
from tori_py.starlette.context import RequestContext, _set_context


def build_starlette_routes(
    plans: tuple[RoutePlan, ...],
    pipeline: PipelineExecutor,
    *,
    application_id: str,
    body_size_limit: int,
) -> list[Route]:
    return [
        Route(
            plan.path,
            endpoint=_endpoint(
                plan,
                pipeline,
                application_id=application_id,
                body_size_limit=body_size_limit,
            ),
            methods=[plan.method],
        )
        for plan in plans
    ]


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
                    "with Starlette RequestContext",
                    code="route.invalid_binding",
                )


def _endpoint(
    plan: RoutePlan,
    pipeline: PipelineExecutor,
    *,
    application_id: str,
    body_size_limit: int,
):
    async def handle(request: Request) -> Response:
        request_scope = current_request_scope()
        if request_scope is None:
            raise HttpException(500, "Request scope is unavailable.")
        context = RequestContext(
            request=request,
            scope=request_scope,
            module_identity=plan.module_id,
            application=application_id,
            route=plan.route_id,
            request_id_value=cast(str, request.scope["tori_py_request_id"]),
        )
        # RequestScopeMiddleware owns the final reset after response and cleanup.
        _set_context(context)
        body_stream: _StarletteBodyStream | None = None

        def bind_body_stream(max_bytes: int) -> _StarletteBodyStream:
            nonlocal body_stream
            body_stream = _StarletteBodyStream(request, max_bytes)
            return body_stream

        async def bind_arguments() -> dict[str, object]:
            return await _bind_arguments(
                plan,
                request,
                context,
                body_size_limit=body_size_limit,
                bind_body_stream=bind_body_stream,
            )

        async def validate_result() -> None:
            if body_stream is not None and not body_stream.complete:
                raise HttpException(400, "Request body stream was not fully consumed.")

        async def encode_result(result: object) -> Response:
            return await _encode_pipeline_result(
                result,
                plan.status_code,
                request,
                plan.response_headers,
            )

        try:
            result = await pipeline.run(
                plan,
                context,
                request_scope,
                bind_arguments=bind_arguments,
                encode_result=encode_result,
                validate_result=validate_result,
            )
            if not isinstance(result, Response):
                raise HttpException(500, "Pipeline did not produce a response.")
            return result
        finally:
            if body_stream is not None:
                await body_stream.aclose()

    return handle


async def _bind_arguments(
    plan: RoutePlan,
    request: Request,
    context: RequestContext,
    *,
    body_size_limit: int,
    bind_body_stream: Callable[[int], object],
) -> dict[str, object]:
    arguments: dict[str, object] = {}
    if plan.rejects_body:
        await _reject_request_body(request, body_size_limit)
    body_loaded = False
    body_value: object = None
    for parameter in plan.parameters:
        if parameter.kind == "inject":
            value = await context.resolver.resolve(cast(Token, parameter.token))
        elif parameter.kind == "context":
            value = context
        elif parameter.kind == "body":
            if body_loaded:
                raise HttpException(400, "A request body may only be bound once.")
            body_value = await _read_json_body(request, body_size_limit)
            body_loaded = True
            value = body_value
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


async def _reject_request_body(request: Request, limit: int) -> None:
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HttpException(413, "Request body exceeds the configured limit.")
    if size:
        raise HttpException(400, "Request body is not allowed.")


def _read_http_value(request: Request, parameter: ParameterPlan) -> object:
    source = cast(str, parameter.source)
    if parameter.kind == "path":
        return request.path_params.get(source, _MISSING)
    if parameter.kind == "query":
        return _collapse_values(request.query_params.getlist(source))
    if parameter.kind == "header":
        return _collapse_values(request.headers.getlist(source))
    if parameter.kind == "cookie":
        return request.cookies.get(source, _MISSING)
    raise HttpException(500, "Unknown route binding kind.")


async def _read_json_body(request: Request, limit: int) -> object:
    if "tori_py_body" in request.scope:
        return request.scope["tori_py_body"]
    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().casefold()
    if media_type != "application/json" and not media_type.endswith("+json"):
        raise HttpException(415, "Request body must use a JSON media type.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HttpException(413, "Request body exceeds the configured limit.")
        chunks.append(chunk)
    try:
        value = json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HttpException(400, "Request body contains malformed JSON.") from error
    request.scope["tori_py_body"] = value
    return value


class _StarletteBodyStream:
    def __init__(self, request: Request, max_bytes: int) -> None:
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
            chunk = message.get("body", b"")
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


async def _encode_result(
    result: object,
    status_code: int,
    request: Request,
    response_headers: tuple[ResponseHeaderMetadata, ...] = (),
) -> Response:
    if isinstance(result, HttpResponse):
        request_id = request.scope.get("tori_py_request_id")
        headers = {
            name: value
            for name, value in result.headers.items()
            if name.casefold() != "x-request-id"
        }
        if isinstance(request_id, str):
            headers["X-Request-ID"] = request_id
        return Response(
            result.content,
            status_code=result.status_code,
            headers=headers,
        )
    if isinstance(result, Response):
        request_id = request.scope.get("tori_py_request_id")
        if isinstance(request_id, str):
            result.headers["X-Request-ID"] = request_id
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
    request_id = request.scope.get("tori_py_request_id")
    if isinstance(request_id, str):
        headers["X-Request-ID"] = request_id
    return Response(
        content,
        status_code=status_code,
        headers=headers,
        media_type="application/json",
    )


async def _encode_pipeline_result(
    result: object,
    status_code: int,
    request: Request,
    response_headers: tuple[ResponseHeaderMetadata, ...] = (),
) -> Response:
    if isinstance(result, PipelineResult):
        if result.is_response and not isinstance(
            result.value, (HttpResponse, Response)
        ):
            raise HttpException(500, "Pipeline response is not an HTTP response.")
        result = result.value
    return await _encode_result(result, status_code, request, response_headers)


def _collapse_values(values: list[str]) -> object:
    if not values:
        return _MISSING
    return values[0] if len(values) == 1 else values


_MISSING = object()

__all__ = ["build_starlette_routes", "validate_context_bindings"]
