"""Register framework HTTP route plans with native Starlette routing."""

from __future__ import annotations

import json
from typing import cast

import msgspec
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from nestpy.core.errors import BootstrapError
from nestpy.core.protocols import PipelineResult
from nestpy.core.providers import Token
from nestpy.http.context import current_request_scope
from nestpy.http.errors import HttpException
from nestpy.http.pipeline import PipelineExecutor
from nestpy.http.routes import ParameterPlan, RoutePlan
from nestpy.starlette.context import RequestContext, _set_context


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
            request_id_value=cast(str, request.scope["nestpy_request_id"]),
        )
        # RequestScopeMiddleware owns the final reset after response and cleanup.
        _set_context(context)

        async def bind_arguments() -> dict[str, object]:
            return await _bind_arguments(
                plan,
                request,
                context,
                body_size_limit=body_size_limit,
            )

        async def encode_result(result: object) -> Response:
            return await _encode_pipeline_result(
                result,
                plan.status_code,
                request,
            )

        result = await pipeline.run(
            plan,
            context,
            request_scope,
            bind_arguments=bind_arguments,
            encode_result=encode_result,
        )
        if not isinstance(result, Response):
            raise HttpException(500, "Pipeline did not produce a response.")
        return result

    return handle


async def _bind_arguments(
    plan: RoutePlan,
    request: Request,
    context: RequestContext,
    *,
    body_size_limit: int,
) -> dict[str, object]:
    arguments: dict[str, object] = {}
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
    if "nestpy_body" in request.scope:
        return request.scope["nestpy_body"]
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
    request.scope["nestpy_body"] = value
    return value


async def _encode_result(
    result: object,
    status_code: int,
    request: Request,
) -> Response:
    if isinstance(result, Response):
        request_id = request.scope.get("nestpy_request_id")
        if isinstance(request_id, str):
            result.headers["X-Request-ID"] = request_id
        return result
    try:
        content = msgspec.json.encode(result)
    except (TypeError, ValueError) as error:
        raise HttpException(
            500, "Handler result could not be encoded as JSON."
        ) from error
    request_id = request.scope.get("nestpy_request_id")
    headers = {"X-Request-ID": request_id} if isinstance(request_id, str) else None
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
) -> Response:
    if isinstance(result, PipelineResult):
        if result.is_response and not isinstance(result.value, Response):
            raise HttpException(500, "Pipeline response is not a Starlette response.")
        result = result.value
    return await _encode_result(result, status_code, request)


def _collapse_values(values: list[str]) -> object:
    if not values:
        return _MISSING
    return values[0] if len(values) == 1 else values


_MISSING = object()

__all__ = ["build_starlette_routes", "validate_context_bindings"]
