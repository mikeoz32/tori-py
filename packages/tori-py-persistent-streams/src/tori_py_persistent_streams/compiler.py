"""Global direct-method stream handler and publisher Protocol compilation."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Annotated, get_args, get_origin, get_type_hints
from uuid import UUID

from tori_py import (
    DiscoveryService,
    ModuleId,
    ModulesContainer,
    ProviderRef,
    Token,
    get_pipeline_metadata,
)
from tori_py_persistent_streams_core import PublishReceipt

from tori_py_persistent_streams.contexts import StreamContext
from tori_py_persistent_streams.decorators import (
    StreamHeader,
    StreamHeaders,
    StreamInject,
    StreamOffset,
    StreamPartition,
    StreamPayload,
    StreamRecordContext,
    get_stream_handler_metadata,
    get_stream_publish_metadata,
)
from tori_py_persistent_streams.errors import (
    StreamConfigurationError,
    StreamHandlerCompilationError,
)
from tori_py_persistent_streams.plans import (
    StreamHandlerPlan,
    StreamHandlerRegistry,
    StreamParameterPlan,
    StreamPipelinePlan,
)


def compile_discovered_stream_handlers(
    discovery: DiscoveryService,
    modules: ModulesContainer,
    *,
    known_streams: Iterable[str],
) -> StreamHandlerRegistry:
    """Compile all direct stream handlers from the final controller graph."""

    known = frozenset(known_streams)
    plans: list[StreamHandlerPlan] = []
    subscriptions: set[tuple[str, str]] = set()
    for view in discovery.get_controllers():
        implementation = view.implementation
        if implementation is None:
            raise StreamHandlerCompilationError(
                f"controller {view.ref.token!r} has no static implementation"
            )
        for plan in compile_controller_stream_handlers(
            view.ref.module_id, implementation, modules
        ):
            plan = replace(plan, controller_ref=view.ref)
            key = (plan.metadata.stream, plan.metadata.consumer_group)
            if plan.metadata.stream not in known:
                raise StreamHandlerCompilationError(
                    f"handler {plan.handler_id} references unknown stream"
                )
            if key in subscriptions:
                raise StreamHandlerCompilationError(
                    f"duplicate stream subscription {key!r}"
                )
            subscriptions.add(key)
            plans.append(plan)
    return StreamHandlerRegistry(tuple(plans))


def compile_controller_stream_handlers(
    module_id: ModuleId,
    controller: type[object],
    modules: ModulesContainer,
) -> tuple[StreamHandlerPlan, ...]:
    """Compile only methods directly declared on one controller class."""

    plans: list[StreamHandlerPlan] = []
    for method_name, candidate in controller.__dict__.items():
        if not inspect.isfunction(candidate):
            continue
        metadata = get_stream_handler_metadata(candidate)
        if metadata is None:
            continue
        if not inspect.iscoroutinefunction(candidate):
            raise StreamHandlerCompilationError(
                f"handler {controller.__qualname__}.{method_name} must be async"
            )
        parameters, payload_type, return_type = _compile_signature(
            candidate, module_id, modules
        )
        if return_type is not None and return_type is not type(None):
            raise StreamHandlerCompilationError(
                f"handler {controller.__qualname__}.{method_name} must return None"
            )
        plans.append(
            StreamHandlerPlan(
                module_id,
                ProviderRef(module_id, controller),
                controller,
                method_name,
                candidate,
                metadata,
                parameters,
                payload_type,
                _pipeline(controller, module_id, modules),
                _pipeline(candidate, module_id, modules),
            )
        )
    return tuple(plans)


def validate_publisher_protocol(
    protocol: type[object], payload_type: type[object]
) -> tuple[str, ...]:
    """Validate explicitly decorated async Protocol methods before startup."""

    if not getattr(protocol, "_is_protocol", False):
        raise StreamConfigurationError("publisher token must be a typing.Protocol")
    methods: list[str] = []
    for name, candidate in protocol.__dict__.items():
        if isinstance(candidate, (classmethod, staticmethod)):
            candidate = candidate.__func__
        if not inspect.isfunction(candidate):
            continue
        if name.startswith("__") and name.endswith("__"):
            continue
        metadata = get_stream_publish_metadata(candidate)
        if metadata is None:
            raise StreamConfigurationError(
                f"publisher method {protocol.__qualname__}.{name} requires "
                "@stream_publish"
            )
        if metadata.payload is not payload_type:
            raise StreamConfigurationError(
                f"publisher method {protocol.__qualname__}.{name} payload mismatch"
            )
        if not inspect.iscoroutinefunction(candidate):
            raise StreamConfigurationError("publisher Protocol methods must be async")
        signature = inspect.signature(candidate)
        hints = get_type_hints(candidate, include_extras=True)
        parameters = tuple(signature.parameters.values())
        if len(parameters) < 2 or parameters[1].annotation is inspect.Parameter.empty:
            raise StreamConfigurationError(
                "publisher Protocol method requires an annotated payload"
            )
        if hints.get(parameters[1].name, parameters[1].annotation) is not payload_type:
            raise StreamConfigurationError("publisher payload annotation mismatch")
        if parameters[1].default is not inspect.Parameter.empty:
            raise StreamConfigurationError(
                "publisher Protocol payload cannot have a default"
            )
        optional = {parameter.name: parameter for parameter in parameters[2:]}
        if set(optional) - {"record_id", "headers"} or any(
            parameter.kind
            in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
            for parameter in parameters
        ):
            raise StreamConfigurationError(
                "publisher Protocol method has unsupported parameters"
            )
        if "record_id" not in optional:
            raise StreamConfigurationError(
                "publisher Protocol method requires optional record_id"
            )
        record_id = optional["record_id"]
        if (
            record_id.kind is not inspect.Parameter.KEYWORD_ONLY
            or record_id.default is not None
            or hints.get("record_id") != UUID | None
        ):
            raise StreamConfigurationError(
                "publisher record_id must be keyword-only UUID | None = None"
            )
        if hints.get("return") is not PublishReceipt:
            raise StreamConfigurationError(
                "publisher Protocol methods must return PublishReceipt"
            )
        headers = optional.get("headers")
        if headers is not None and (
            headers.kind is not inspect.Parameter.KEYWORD_ONLY
            or headers.default is not None
        ):
            raise StreamConfigurationError(
                "publisher headers must be keyword-only with a None default"
            )
        methods.append(name)
    if not methods:
        raise StreamConfigurationError(
            "publisher Protocol requires at least one @stream_publish method"
        )
    return tuple(methods)


def _compile_signature(
    handler: Callable[..., object],
    module_id: ModuleId,
    modules: ModulesContainer,
) -> tuple[tuple[StreamParameterPlan, ...], type[object], object]:
    try:
        signature = inspect.signature(handler)
        hints = get_type_hints(handler, include_extras=True)
    except (TypeError, ValueError, NameError) as error:
        raise StreamHandlerCompilationError(
            "handler annotations could not be resolved"
        ) from error
    plans: list[StreamParameterPlan] = []
    payload_types: list[type[object]] = []
    for index, parameter in enumerate(signature.parameters.values()):
        if index == 0:
            continue
        if parameter.kind in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            raise StreamHandlerCompilationError("stream handler parameters cannot vary")
        annotation = hints.get(parameter.name, parameter.annotation)
        base, markers = _markers(annotation)
        if len(markers) != 1:
            raise StreamHandlerCompilationError(
                f"parameter {parameter.name} requires exactly one stream marker"
            )
        kind, source, token = _marker(markers[0])
        if kind == "payload":
            if not isinstance(base, type):
                raise StreamHandlerCompilationError("payload annotation must be a type")
            payload_types.append(base)
        if kind == "context" and not (
            isinstance(base, type) and issubclass(StreamContext, base)
        ):
            raise StreamHandlerCompilationError("context annotation is invalid")
        provider_ref = None
        if token is not None:
            view = modules.provider(module_id, token)
            if view is None:
                raise StreamHandlerCompilationError(
                    f"provider token {token!r} is not visible from handler module"
                )
            provider_ref = view.ref
        plans.append(
            StreamParameterPlan(
                parameter.name,
                base,
                kind,
                source,
                token,
                provider_ref,
                parameter.default,
                parameter.default is not inspect.Parameter.empty,
            )
        )
    if len(payload_types) != 1:
        raise StreamHandlerCompilationError(
            "stream handler requires exactly one StreamPayload parameter"
        )
    return (
        tuple(plans),
        payload_types[0],
        hints.get("return", signature.return_annotation),
    )


def _markers(annotation: object) -> tuple[object, tuple[object, ...]]:
    if get_origin(annotation) is not Annotated:
        return annotation, ()
    arguments = get_args(annotation)
    supported = (
        StreamPayload,
        StreamRecordContext,
        StreamHeaders,
        StreamHeader,
        StreamPartition,
        StreamOffset,
        StreamInject,
    )
    markers = tuple(value for value in arguments[1:] if isinstance(value, supported))
    return arguments[0], markers


def _marker(marker: object) -> tuple[str, str | None, Token | None]:
    if isinstance(marker, StreamPayload):
        return "payload", None, None
    if isinstance(marker, StreamRecordContext):
        return "context", None, None
    if isinstance(marker, StreamHeaders):
        return "headers", None, None
    if isinstance(marker, StreamHeader):
        return "header", marker.name, None
    if isinstance(marker, StreamPartition):
        return "partition", None, None
    if isinstance(marker, StreamOffset):
        return "offset", None, None
    if isinstance(marker, StreamInject):
        return "inject", None, marker.token
    raise StreamHandlerCompilationError("unsupported stream parameter marker")


def _pipeline(
    target: object, module_id: ModuleId, modules: ModulesContainer
) -> StreamPipelinePlan:
    values = {
        kind: get_pipeline_metadata(target, kind)
        for kind in ("guards", "pipes", "interceptors", "filters")
    }
    refs = tuple(
        (kind, _provider_ref(modules, module_id, binding))
        for kind, bindings in values.items()
        for binding in bindings
        if isinstance(binding, (str, type))
    )
    return StreamPipelinePlan(
        values["guards"],
        values["pipes"],
        values["interceptors"],
        values["filters"],
        refs,
    )


def _provider_ref(
    modules: ModulesContainer, module_id: ModuleId, token: Token
) -> ProviderRef:
    view = modules.provider(module_id, token)
    if view is None:
        raise StreamHandlerCompilationError(
            f"pipeline provider {token!r} is not visible from handler module"
        )
    return view.ref


__all__ = [
    "compile_controller_stream_handlers",
    "compile_discovered_stream_handlers",
    "validate_publisher_protocol",
]
