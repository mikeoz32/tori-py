"""Transport-independent HTTP controller and route compilation."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Annotated, cast, get_args, get_origin, get_type_hints

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
    get_pipeline_metadata,
    get_route_metadata,
    get_status_metadata,
)
from nestpy.core.pipeline import PipelineBindings
from nestpy.core.protocols import ScopedResolver
from nestpy.core.providers import Inject, Token
from nestpy.http.context import HttpContext
from nestpy.http.response import ResponseHeaderMetadata, get_response_header_metadata


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
    handler: Callable[..., object]
    method: str
    path: str
    route_id: str
    status_code: int
    parameters: tuple[ParameterPlan, ...]
    controller_pipeline: PipelineBindings
    route_pipeline: PipelineBindings
    return_annotation: object = inspect.Signature.empty
    response_headers: tuple[ResponseHeaderMetadata, ...] = ()


def compile_routes(graph: CompiledGraph) -> tuple[RoutePlan, ...]:
    plans: list[RoutePlan] = []
    reserved: set[tuple[str, str]] = set()
    for module in graph.modules:
        for controller in module.spec.controllers:
            controller_plans = compile_controller_routes(module.module_id, controller)
            for plan in controller_plans:
                _reserve_route(plan.method, plan.path, reserved)
            plans.extend(controller_plans)
    return tuple(plans)


def compile_controller_routes(
    module_id: ModuleId,
    controller: type[object],
) -> tuple[RoutePlan, ...]:
    """Compile the canonical unbound route mappings for one controller."""

    controller_metadata = get_controller_metadata(controller)
    if controller_metadata is None:
        raise BootstrapError(
            "controller must have controller metadata",
            code="controller.invalid_declaration",
            details={"controller": controller.__qualname__},
        )
    plans: list[RoutePlan] = []
    reserved: set[tuple[str, str]] = set()
    for method_name, handler in controller.__dict__.items():
        route_metadata = get_route_metadata(handler)
        if route_metadata is None:
            continue
        path = _join_paths(controller_metadata.prefix, route_metadata.path)
        _reserve_route(route_metadata.method, path, reserved)
        parameters, return_annotation = _compile_signature(handler)
        status_metadata = get_status_metadata(handler)
        plans.append(
            RoutePlan(
                module_id=module_id,
                controller=controller,
                method_name=method_name,
                handler=handler,
                method=route_metadata.method,
                path=path,
                route_id=f"{route_metadata.method} {path}",
                status_code=(
                    200 if status_metadata is None else status_metadata.status_code
                ),
                parameters=parameters,
                controller_pipeline=_pipeline_bindings(controller),
                route_pipeline=_pipeline_bindings(handler),
                return_annotation=return_annotation,
                response_headers=get_response_header_metadata(handler),
            )
        )
    return tuple(plans)


def _reserve_route(
    method: str,
    path: str,
    reserved: set[tuple[str, str]],
) -> None:
    identities = {(method, path)}
    if method == "GET":
        identities.add(("HEAD", path))
    if reserved.intersection(identities):
        raise BootstrapError(
            "duplicate controller route",
            code="route.duplicate",
            details={"method": method, "path": path},
        )
    reserved.update(identities)


async def bind_routes(
    plans: tuple[RoutePlan, ...],
    resolver_for: Callable[[ModuleId], ScopedResolver],
) -> tuple[RoutePlan, ...]:
    """Bind compiled plans to their started singleton controller methods."""

    bound: list[RoutePlan] = []
    for plan in plans:
        controller = await resolver_for(plan.module_id).resolve(plan.controller)
        handler = getattr(controller, plan.method_name, None)
        if not callable(handler):
            raise BootstrapError(
                "compiled controller handler is not callable",
                code="controller.invalid_signature",
                details={"controller": plan.controller.__qualname__},
            )
        bound.append(replace(plan, handler=handler))
    return tuple(bound)


def _compile_signature(
    handler: object,
) -> tuple[tuple[ParameterPlan, ...], object]:
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
            not isinstance(base, type) or not issubclass(base, HttpContext)
        ):
            raise BootstrapError(
                f"route context parameter {parameter.name} must use HttpContext",
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
    return (
        tuple(plans),
        hints.get("return", signature.return_annotation),
    )


def _pipeline_bindings(target: object) -> PipelineBindings:
    return PipelineBindings(
        middleware=get_pipeline_metadata(target, "middleware"),
        guards=get_pipeline_metadata(target, "guards"),
        pipes=get_pipeline_metadata(target, "pipes"),
        interceptors=get_pipeline_metadata(target, "interceptors"),
        filters=get_pipeline_metadata(target, "filters"),
    )


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


__all__ = [
    "ParameterPlan",
    "RoutePlan",
    "bind_routes",
    "compile_controller_routes",
    "compile_routes",
]
