"""Transport-independent WebSocket gateway compilation."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Annotated, cast, get_args, get_origin, get_type_hints

from tori_py.core.compiler import CompiledGraph, ModuleId, ProviderRef
from tori_py.core.errors import BootstrapError
from tori_py.core.metadata import (
    Body,
    BodyStream,
    Context,
    Cookie,
    Header,
    Path,
    Query,
    Socket,
    get_pipeline_metadata,
    get_websocket_gateway_metadata,
)
from tori_py.core.pipeline import PipelineBindings
from tori_py.core.protocols import QualifiedScopedResolver
from tori_py.core.providers import ClassProvider, Inject, Scope, Token
from tori_py.websocket.context import WebSocketContext


@dataclass(frozen=True, slots=True)
class WebSocketParameterPlan:
    name: str
    annotation: object
    kind: str
    source: str | None
    token: Token | None
    default: object
    has_default: bool


@dataclass(frozen=True, slots=True)
class WebSocketPlan:
    module_id: ModuleId
    gateway_ref: ProviderRef
    gateway: type[object]
    method_name: str
    handler: Callable[..., object]
    path: str
    route_id: str
    parameters: tuple[WebSocketParameterPlan, ...]
    gateway_pipeline: PipelineBindings
    handler_pipeline: PipelineBindings
    return_annotation: object = inspect.Signature.empty


def compile_websocket_routes(graph: CompiledGraph) -> tuple[WebSocketPlan, ...]:
    plans: list[WebSocketPlan] = []
    reserved: set[str] = set()
    for module in graph.modules:
        for provider in module.providers:
            declaration = provider.declaration
            if not isinstance(declaration, ClassProvider):
                continue
            gateway = cast(type[object], declaration.use_class)
            if get_websocket_gateway_metadata(gateway) is None:
                continue
            if provider.scope is not Scope.SINGLETON:
                raise BootstrapError(
                    "WebSocket gateways must be singleton providers",
                    code="gateway.invalid_declaration",
                    details={"gateway": gateway.__qualname__},
                )
            plan = compile_websocket_gateway(
                module.module_id,
                gateway,
                gateway_ref=provider.canonical,
            )
            if plan.path in reserved:
                raise BootstrapError(
                    "duplicate WebSocket gateway path",
                    code="gateway.duplicate",
                    details={"path": plan.path},
                )
            reserved.add(plan.path)
            plans.append(plan)
    return tuple(plans)


def compile_websocket_gateway(
    module_id: ModuleId,
    gateway: type[object],
    *,
    gateway_ref: ProviderRef | None = None,
) -> WebSocketPlan:
    metadata = get_websocket_gateway_metadata(gateway)
    if metadata is None:
        raise BootstrapError(
            "WebSocket gateway metadata is required",
            code="gateway.invalid_declaration",
            details={"gateway": gateway.__qualname__},
        )
    handler = gateway.__dict__.get("handle")
    if not callable(handler) or not inspect.iscoroutinefunction(handler):
        raise BootstrapError(
            "WebSocket gateway requires one direct async handle method",
            code="gateway.invalid_signature",
            details={"gateway": gateway.__qualname__},
        )
    parameters, return_annotation = _compile_signature(handler)
    path = _normalize_path(metadata.path)
    return WebSocketPlan(
        module_id=module_id,
        gateway_ref=(
            ProviderRef(module_id, gateway) if gateway_ref is None else gateway_ref
        ),
        gateway=gateway,
        method_name="handle",
        handler=handler,
        path=path,
        route_id=f"WS {path}",
        parameters=parameters,
        gateway_pipeline=_pipeline_bindings(gateway),
        handler_pipeline=_pipeline_bindings(handler),
        return_annotation=return_annotation,
    )


async def bind_websocket_routes(
    plans: tuple[WebSocketPlan, ...],
    resolver_for: Callable[[ModuleId], QualifiedScopedResolver],
) -> tuple[WebSocketPlan, ...]:
    bound: list[WebSocketPlan] = []
    for plan in plans:
        gateway = await resolver_for(plan.module_id).resolve_ref(plan.gateway_ref)
        handler = getattr(gateway, plan.method_name, None)
        if not callable(handler):
            raise BootstrapError(
                "compiled WebSocket gateway handler is not callable",
                code="gateway.invalid_signature",
                details={"gateway": plan.gateway.__qualname__},
            )
        bound.append(replace(plan, handler=handler))
    return tuple(bound)


def _compile_signature(
    handler: object,
) -> tuple[tuple[WebSocketParameterPlan, ...], object]:
    try:
        signature = inspect.signature(cast(Callable[..., object], handler))
        hints = get_type_hints(handler, include_extras=True)
    except (TypeError, ValueError, NameError) as error:
        raise BootstrapError(
            "WebSocket gateway annotations could not be inspected",
            code="gateway.invalid_signature",
        ) from error
    plans: list[WebSocketParameterPlan] = []
    socket_count = 0
    for parameter in signature.parameters.values():
        if parameter.name == "self":
            continue
        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            raise BootstrapError(
                "WebSocket gateway variadic parameters are not supported",
                code="gateway.invalid_binding",
            )
        annotation = hints.get(parameter.name, parameter.annotation)
        base, markers = _annotation_markers(annotation)
        if len(markers) != 1:
            raise BootstrapError(
                f"WebSocket parameter {parameter.name} requires exactly one marker",
                code="gateway.invalid_binding",
            )
        kind, source, token = _marker_details(markers[0])
        if kind == "socket":
            socket_count += 1
        if kind == "context" and (
            not isinstance(base, type) or not issubclass(base, WebSocketContext)
        ):
            raise BootstrapError(
                f"WebSocket context parameter {parameter.name} must use "
                "WebSocketContext",
                code="gateway.invalid_binding",
            )
        plans.append(
            WebSocketParameterPlan(
                name=parameter.name,
                annotation=base,
                kind=kind,
                source=source,
                token=token,
                default=parameter.default,
                has_default=parameter.default is not inspect.Parameter.empty,
            )
        )
    if socket_count != 1:
        raise BootstrapError(
            "WebSocket gateway requires exactly one Socket binding",
            code="gateway.invalid_binding",
        )
    return tuple(plans), hints.get("return", signature.return_annotation)


def _annotation_markers(annotation: object) -> tuple[object, list[object]]:
    if get_origin(annotation) is not Annotated:
        return annotation, []
    args = get_args(annotation)
    markers = [marker for marker in args[1:] if _is_marker(marker)]
    if len(markers) != len(args[1:]):
        return args[0], []
    return args[0], markers


def _marker_details(marker: object) -> tuple[str, str | None, Token | None]:
    if isinstance(marker, Socket):
        return "socket", None, None
    if isinstance(marker, Context):
        return "context", None, None
    if isinstance(marker, Path):
        return "path", marker.name, None
    if isinstance(marker, Query):
        return "query", marker.name, None
    if isinstance(marker, Header):
        return "header", marker.name, None
    if isinstance(marker, Cookie):
        return "cookie", marker.name, None
    if isinstance(marker, Inject):
        return "inject", None, marker.token
    raise BootstrapError(
        "unsupported WebSocket binding marker",
        code="gateway.invalid_binding",
    )


def _is_marker(value: object) -> bool:
    return isinstance(
        value,
        (Socket, Context, Path, Query, Header, Cookie, Inject, Body, BodyStream),
    )


def _pipeline_bindings(target: object) -> PipelineBindings:
    return PipelineBindings(
        middleware=get_pipeline_metadata(target, "middleware"),
        guards=get_pipeline_metadata(target, "guards"),
        pipes=get_pipeline_metadata(target, "pipes"),
        interceptors=get_pipeline_metadata(target, "interceptors"),
        filters=get_pipeline_metadata(target, "filters"),
    )


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    return path if path.startswith("/") else f"/{path}"


__all__ = [
    "WebSocketParameterPlan",
    "WebSocketPlan",
    "bind_websocket_routes",
    "compile_websocket_gateway",
    "compile_websocket_routes",
]
