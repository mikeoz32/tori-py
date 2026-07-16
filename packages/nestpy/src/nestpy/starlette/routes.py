"""Controller route plans and raw Starlette request binding."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, cast, get_args, get_origin, get_type_hints

import msgspec
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from nestpy.core.compiler import CompiledGraph, ModuleId
from nestpy.core.errors import BootstrapError
from nestpy.core.metadata import (
    Body,
    Context,
    Cookie,
    Header,
    Path,
    Query,
    get_controller_metadata,
    get_route_metadata,
    get_status_metadata,
)
from nestpy.core.providers import Inject, Token
from nestpy.core.runtime import ApplicationKernel
from nestpy.starlette.context import (
    RequestContext,
    _reset_context,
    _set_context,
    current_request_scope,
)
from nestpy.starlette.errors import HttpException


@dataclass(frozen=True, slots=True)
class ParameterPlan:
    name: str
    annotation: object
    kind: str
    source: str | None
    token: Token | None
    default: object
    has_default: bool


@dataclass(frozen=True, slots=True)
class RoutePlan:
    module_id: ModuleId
    controller: type[object]
    method_name: str
    method: str
    path: str
    route_id: str
    status_code: int
    parameters: tuple[ParameterPlan, ...]


def compile_routes(graph: CompiledGraph) -> tuple[RoutePlan, ...]:
    plans: list[RoutePlan] = []
    reserved: set[tuple[str, str]] = set()
    for module in graph.modules:
        for controller in module.spec.controllers:
            controller_metadata = get_controller_metadata(controller)
            if controller_metadata is None:
                raise BootstrapError(
                    "controller must have controller metadata",
                    code="controller.invalid_declaration",
                    details={"controller": controller.__qualname__},
                )
            for method_name, handler in controller.__dict__.items():
                route_metadata = get_route_metadata(handler)
                if route_metadata is None:
                    continue
                path = _join_paths(controller_metadata.prefix, route_metadata.path)
                identities = {(route_metadata.method, path)}
                if route_metadata.method == "GET":
                    identities.add(("HEAD", path))
                if reserved.intersection(identities):
                    raise BootstrapError(
                        "duplicate controller route",
                        code="route.duplicate",
                        details={
                            "method": route_metadata.method,
                            "path": path,
                        },
                    )
                reserved.update(identities)
                parameters = _compile_parameters(handler)
                status_metadata = get_status_metadata(handler)
                plans.append(
                    RoutePlan(
                        module_id=module.module_id,
                        controller=controller,
                        method_name=method_name,
                        method=route_metadata.method,
                        path=path,
                        route_id=f"{route_metadata.method} {path}",
                        status_code=(
                            200
                            if status_metadata is None
                            else status_metadata.status_code
                        ),
                        parameters=parameters,
                    )
                )
    return tuple(plans)


def build_starlette_routes(
    plans: tuple[RoutePlan, ...],
    kernel: ApplicationKernel,
    *,
    application_id: str,
    body_size_limit: int,
) -> list[Route]:
    routes: list[Route] = []
    for plan in plans:
        endpoint = _endpoint(
            plan,
            kernel,
            application_id=application_id,
            body_size_limit=body_size_limit,
        )
        routes.append(Route(plan.path, endpoint=endpoint, methods=[plan.method]))
    return routes


def _endpoint(
    plan: RoutePlan,
    kernel: ApplicationKernel,
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
        context_token = _set_context(context)
        try:
            controller = await request_scope.resolver_for(plan.module_id).resolve(
                plan.controller
            )
            arguments = await _bind_arguments(
                plan,
                request,
                context,
                body_size_limit=body_size_limit,
            )
            handler = getattr(controller, plan.method_name)
            result = handler(**arguments)
            if inspect.isawaitable(result):
                result = await result
            return await _encode_result(result, plan.status_code, request)
        finally:
            _reset_context(context_token)

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
        values = request.query_params.getlist(source)
        return _collapse_values(values)
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
    result: object, status_code: int, request: Request
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


def _compile_parameters(handler: object) -> tuple[ParameterPlan, ...]:
    try:
        signature = inspect.signature(cast(Callable[..., object], handler))
        hints = get_type_hints(handler, include_extras=True)
    except (TypeError, ValueError, NameError) as error:
        raise BootstrapError(
            "controller route annotations could not be inspected",
            code="controller.invalid_signature",
        ) from error
    plans: list[ParameterPlan] = []
    body_count = 0
    for parameter in signature.parameters.values():
        if parameter.name == "self":
            continue
        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            raise BootstrapError(
                "route variadic parameters are not supported",
                code="route.invalid_binding",
            )
        annotation = hints.get(parameter.name, parameter.annotation)
        base, markers = _annotation_markers(annotation)
        if len(markers) != 1:
            raise BootstrapError(
                f"route parameter {parameter.name} requires exactly one binding marker",
                code="route.invalid_binding",
            )
        marker = markers[0]
        kind, source, token = _marker_details(marker)
        if kind == "body":
            body_count += 1
        if kind in {"path", "query", "header", "cookie"} and source is None:
            raise BootstrapError(
                f"route parameter {parameter.name} requires a source name",
                code="route.invalid_binding",
            )
        if kind == "context" and (
            not isinstance(base, type) or not issubclass(base, RequestContext)
        ):
            raise BootstrapError(
                f"route context parameter {parameter.name} must use RequestContext",
                code="route.invalid_binding",
            )
        plans.append(
            ParameterPlan(
                name=parameter.name,
                annotation=base,
                kind=kind,
                source=source,
                token=token,
                default=parameter.default,
                has_default=parameter.default is not inspect.Parameter.empty,
            )
        )
    if body_count > 1:
        raise BootstrapError(
            "a route may have at most one body binding",
            code="route.invalid_binding",
        )
    return tuple(plans)


def _annotation_markers(annotation: object) -> tuple[object, list[object]]:
    if get_origin(annotation) is not Annotated:
        return annotation, []
    args = get_args(annotation)
    recognized = [marker for marker in args[1:] if _is_marker(marker)]
    if len(recognized) != len(args[1:]):
        return args[0], []
    return args[0], recognized


def _marker_details(marker: object) -> tuple[str, str | None, Token | None]:
    if isinstance(marker, Body):
        return "body", None, None
    if isinstance(marker, Path):
        return "path", marker.name, None
    if isinstance(marker, Query):
        return "query", marker.name, None
    if isinstance(marker, Header):
        return "header", marker.name, None
    if isinstance(marker, Cookie):
        return "cookie", marker.name, None
    if isinstance(marker, Context):
        return "context", None, None
    if isinstance(marker, Inject):
        return "inject", None, marker.token
    raise BootstrapError("unknown route binding marker", code="route.invalid_binding")


def _is_marker(value: object) -> bool:
    return isinstance(value, (Body, Path, Query, Header, Cookie, Context, Inject))


def _join_paths(prefix: str, path: str) -> str:
    if not prefix and not path:
        return "/"
    if not prefix:
        joined = path
    elif not path:
        joined = prefix
    elif prefix.endswith("/") and path.startswith("/"):
        joined = prefix + path[1:]
    elif not prefix.endswith("/") and not path.startswith("/"):
        joined = f"{prefix}/{path}"
    else:
        joined = prefix + path
    return joined if joined.startswith("/") else f"/{joined}"


def _collapse_values(values: list[str]) -> object:
    if not values:
        return _MISSING
    return values[0] if len(values) == 1 else values


_MISSING = object()


__all__ = ["RoutePlan", "compile_routes"]
