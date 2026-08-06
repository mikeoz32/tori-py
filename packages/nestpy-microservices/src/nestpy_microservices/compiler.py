"""Controller discovery and message handler compilation."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Annotated, cast, get_args, get_origin, get_type_hints

from nestpy import (
    DiscoveryService,
    Inject,
    ModuleId,
    ModulesContainer,
    ProviderRef,
    Token,
    get_pipeline_metadata,
)

from nestpy_microservices.contexts import EventContext, RpcContext
from nestpy_microservices.decorators import (
    Context,
    EventDispatchMode,
    Header,
    Headers,
    Payload,
    get_event_handler_metadata,
    get_rpc_metadata,
)
from nestpy_microservices.errors import HandlerCompilationError
from nestpy_microservices.plans import (
    EventHandlerPlan,
    MessageParameterPlan,
    PipelinePlan,
    RpcHandlerPlan,
    ServiceHandlerRegistry,
    is_explicit_none,
)


def compile_controller_message_handlers(
    module_id: ModuleId,
    controller: type[object],
    *,
    modules: ModulesContainer | None = None,
) -> tuple[RpcHandlerPlan | EventHandlerPlan, ...]:
    """Compile direct message metadata from one explicitly registered controller."""

    if not isinstance(module_id, ModuleId):
        raise HandlerCompilationError("module_id must be a ModuleId")
    if not isinstance(controller, type):
        raise HandlerCompilationError("controller must be a class")
    plans: list[RpcHandlerPlan | EventHandlerPlan] = []
    for method_name, candidate in controller.__dict__.items():
        unwrapped = _unwrap_handler(candidate)
        if unwrapped is None:
            if _inherited_message_metadata(controller, method_name):
                raise HandlerCompilationError(
                    f"non-callable override shadows decorated handler "
                    f"{controller.__qualname__}.{method_name}"
                )
            continue
        handler, skip_first_parameter = unwrapped
        rpc_metadata = get_rpc_metadata(handler)
        event_metadata = get_event_handler_metadata(handler)
        if rpc_metadata is not None and event_metadata is not None:
            raise HandlerCompilationError(
                f"handler {controller.__qualname__}.{method_name} has conflicting "
                "RPC and event metadata"
            )
        if rpc_metadata is None and event_metadata is None:
            continue
        if not inspect.iscoroutinefunction(handler):
            raise HandlerCompilationError(
                f"handler {controller.__qualname__}.{method_name} must be async"
            )
        expected_context = RpcContext if rpc_metadata is not None else EventContext
        parameters, return_annotation = _compile_signature(
            handler,
            expected_context,
            module_id,
            modules,
            skip_first_parameter=skip_first_parameter,
        )
        controller_pipeline = _pipeline_plan(controller, module_id, modules)
        method_pipeline = _pipeline_plan(handler, module_id, modules)
        controller_ref = ProviderRef(module_id, controller)
        if rpc_metadata is not None:
            if return_annotation is inspect.Signature.empty:
                raise HandlerCompilationError(
                    f"RPC handler {controller.__qualname__}.{method_name} must "
                    "declare a return annotation"
                )
            plans.append(
                RpcHandlerPlan(
                    module_id=module_id,
                    controller_ref=controller_ref,
                    controller=controller,
                    method_name=method_name,
                    handler=handler,
                    metadata=rpc_metadata,
                    parameters=parameters,
                    return_annotation=return_annotation,
                    controller_pipeline=controller_pipeline,
                    method_pipeline=method_pipeline,
                )
            )
        else:
            assert event_metadata is not None
            if not is_explicit_none(return_annotation):
                raise HandlerCompilationError(
                    f"event handler {controller.__qualname__}.{method_name} must "
                    "return None"
                )
            plans.append(
                EventHandlerPlan(
                    module_id=module_id,
                    controller_ref=controller_ref,
                    controller=controller,
                    method_name=method_name,
                    handler=handler,
                    metadata=event_metadata,
                    parameters=parameters,
                    return_annotation=return_annotation,
                    controller_pipeline=controller_pipeline,
                    method_pipeline=method_pipeline,
                )
            )
    return tuple(plans)


def compile_service_handler_registry(
    controllers: Iterable[tuple[ModuleId, type[object]]],
    *,
    modules: ModulesContainer | None = None,
) -> ServiceHandlerRegistry:
    """Compile ordered controller registrations into one validated registry."""

    plans: list[RpcHandlerPlan | EventHandlerPlan] = []
    for module_id, controller in controllers:
        plans.extend(
            compile_controller_message_handlers(module_id, controller, modules=modules)
        )
    return _registry_from_plans(plans)


def compile_discovered_service_handlers(
    discovery: DiscoveryService,
    *,
    modules: ModulesContainer | None = None,
) -> ServiceHandlerRegistry:
    """Compile every discovered controller with one discovery call."""

    views = discovery.get_controllers()
    compiled: list[RpcHandlerPlan | EventHandlerPlan] = []
    for view in views:
        implementation = view.implementation
        if implementation is None:
            raise HandlerCompilationError(
                f"controller provider {view.ref.token!r} has no static implementation"
            )
        compiled.extend(
            replace(plan, controller_ref=view.ref)
            for plan in compile_controller_message_handlers(
                view.ref.module_id, implementation, modules=modules
            )
        )
    return _registry_from_plans(compiled)


def qualify_pipeline_plan(
    pipeline: PipelinePlan,
    module_id: ModuleId,
    modules: ModulesContainer,
) -> PipelinePlan:
    """Compile provider-backed pipeline bindings against one module owner."""

    bindings = (
        ("middleware", pipeline.middleware),
        ("guards", pipeline.guards),
        ("pipes", pipeline.pipes),
        ("interceptors", pipeline.interceptors),
        ("filters", pipeline.filters),
    )
    if pipeline.middleware:
        raise HandlerCompilationError(
            "message middleware is unsupported; use guards, pipes, or interceptors"
        )
    return replace(
        pipeline,
        qualified_provider_refs=_qualified_pipeline_refs(bindings, module_id, modules),
    )


def _registry_from_plans(
    plans: Iterable[RpcHandlerPlan | EventHandlerPlan],
) -> ServiceHandlerRegistry:
    rpc_handlers: list[RpcHandlerPlan] = []
    event_handlers: list[EventHandlerPlan] = []
    rpc_targets: set[str] = set()
    event_keys: set[tuple[object, EventDispatchMode, str]] = set()
    for plan in plans:
        if isinstance(plan, RpcHandlerPlan):
            if plan.method in rpc_targets:
                raise HandlerCompilationError(
                    f"duplicate RPC method alias {plan.method!r}"
                )
            rpc_targets.add(plan.method)
            rpc_handlers.append(plan)
            continue
        key = (plan.identity, plan.mode, plan.subscription)
        if key in event_keys:
            raise HandlerCompilationError(
                f"duplicate local event subscription identity {plan.subscription!r}"
            )
        event_keys.add(key)
        event_handlers.append(plan)
    return ServiceHandlerRegistry(tuple(rpc_handlers), tuple(event_handlers))


def _unwrap_handler(candidate: object):
    if isinstance(candidate, staticmethod):
        return candidate.__func__, False
    if isinstance(candidate, classmethod):
        return candidate.__func__, True
    if inspect.isfunction(candidate):
        return candidate, True
    return None


def _inherited_message_metadata(controller: type[object], method_name: str) -> bool:
    for base in controller.__mro__[1:]:
        inherited = base.__dict__.get(method_name)
        if inherited is None:
            continue
        unwrapped = _unwrap_handler(inherited)
        handler = None if unwrapped is None else unwrapped[0]
        if handler is not None and (
            get_rpc_metadata(handler) is not None
            or get_event_handler_metadata(handler) is not None
        ):
            return True
    return False


def _compile_signature(
    handler: object,
    expected_context: type[object],
    module_id: ModuleId,
    modules: ModulesContainer | None,
    *,
    skip_first_parameter: bool,
) -> tuple[tuple[MessageParameterPlan, ...], object]:
    try:
        handler_callable = cast(Callable[..., object], handler)
        signature = inspect.signature(handler_callable)
        hints = get_type_hints(handler, include_extras=True)
    except (TypeError, ValueError, NameError) as error:
        raise HandlerCompilationError(
            "handler annotations could not be resolved"
        ) from error
    plans: list[MessageParameterPlan] = []
    complete_payloads = 0
    for index, parameter in enumerate(signature.parameters.values()):
        if skip_first_parameter and index == 0:
            continue
        if parameter.kind in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            raise HandlerCompilationError(
                f"handler parameter {parameter.name} cannot be variadic"
            )
        annotation = hints.get(parameter.name, parameter.annotation)
        converted_annotation, markers = _annotation_markers(annotation)
        if len(markers) != 1:
            raise HandlerCompilationError(
                f"handler parameter {parameter.name} requires exactly one marker"
            )
        kind, source, token = _marker_details(markers[0])
        annotation_base = _annotation_base(converted_annotation)
        if kind == "context" and not _context_annotation_accepts(
            expected_context, annotation_base
        ):
            raise HandlerCompilationError(
                f"handler context parameter {parameter.name} has the wrong context type"
            )
        if kind == "payload" and source is None:
            complete_payloads += 1
        plans.append(
            MessageParameterPlan(
                name=parameter.name,
                annotation=converted_annotation,
                kind=kind,
                source=source,
                token=token,
                provider_ref=(
                    _provider_ref(modules, module_id, token)
                    if kind == "inject" and token is not None and modules is not None
                    else None
                ),
                default=parameter.default,
                has_default=parameter.default is not inspect.Parameter.empty,
            )
        )
    if complete_payloads > 1:
        raise HandlerCompilationError("a handler may have at most one complete payload")
    return tuple(plans), hints.get("return", signature.return_annotation)


def _annotation_markers(annotation: object) -> tuple[object, tuple[object, ...]]:
    if get_origin(annotation) is not Annotated:
        return annotation, ()
    args = get_args(annotation)
    markers = tuple(
        marker
        for marker in args[1:]
        if isinstance(marker, (Payload, Context, Headers, Header, Inject))
    )
    retained = tuple(marker for marker in args[1:] if marker not in markers)
    converted = Annotated[args[0], *retained] if retained else args[0]
    return converted, markers


def _annotation_base(annotation: object) -> object:
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    return annotation


def _context_annotation_accepts(
    expected_context: type[object], annotation: object
) -> bool:
    if not isinstance(annotation, type):
        return False
    try:
        return issubclass(expected_context, annotation)
    except TypeError:
        return False


def _marker_details(marker: object) -> tuple[str, str | None, Token | None]:
    if isinstance(marker, Payload):
        return "payload", marker.source, None
    if isinstance(marker, Context):
        return "context", None, None
    if isinstance(marker, Headers):
        return "headers", None, None
    if isinstance(marker, Header):
        return "header", marker.name, None
    if isinstance(marker, Inject):
        return "inject", None, marker.token
    raise HandlerCompilationError("unsupported message parameter marker")


def _pipeline_plan(
    target: object,
    module_id: ModuleId,
    modules: ModulesContainer | None,
) -> PipelinePlan:
    bindings = (
        ("middleware", get_pipeline_metadata(target, "middleware")),
        ("guards", get_pipeline_metadata(target, "guards")),
        ("pipes", get_pipeline_metadata(target, "pipes")),
        ("interceptors", get_pipeline_metadata(target, "interceptors")),
        ("filters", get_pipeline_metadata(target, "filters")),
    )
    if bindings[0][1]:
        raise HandlerCompilationError(
            "message middleware is unsupported; use guards, pipes, or interceptors"
        )
    return PipelinePlan(
        middleware=bindings[0][1],
        guards=bindings[1][1],
        pipes=bindings[2][1],
        interceptors=bindings[3][1],
        filters=bindings[4][1],
        qualified_provider_refs=_qualified_pipeline_refs(bindings, module_id, modules),
    )


def _qualified_pipeline_refs(
    bindings: tuple[tuple[str, Iterable[object]], ...],
    module_id: ModuleId,
    modules: ModulesContainer | None,
) -> tuple[tuple[str, ProviderRef], ...]:
    if modules is None:
        return ()
    return tuple(
        (kind, _provider_ref(modules, module_id, value))
        for kind, values in bindings
        for value in values
        if isinstance(value, (str, type))
    )


def _provider_ref(
    modules: ModulesContainer | None,
    module_id: ModuleId,
    token: Token,
) -> ProviderRef:
    if modules is None:
        raise HandlerCompilationError(
            "provider graph is required for token qualification"
        )
    view = modules.provider(module_id, token)
    if view is None:
        raise HandlerCompilationError(
            f"provider token {token!r} is not visible from handler module"
        )
    return view.ref


__all__ = [
    "compile_controller_message_handlers",
    "compile_discovered_service_handlers",
    "compile_service_handler_registry",
    "qualify_pipeline_plan",
]
