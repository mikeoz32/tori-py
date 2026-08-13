"""Immutable compiled stream handler plans."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from tori_py import ModuleId, ProviderRef, Token

from tori_py_persistent_streams.decorators import StreamHandlerMetadata


@dataclass(frozen=True, slots=True)
class StreamParameterPlan:
    name: str
    annotation: object
    kind: str
    source: str | None = None
    token: Token | None = None
    provider_ref: ProviderRef | None = None
    default: object = None
    has_default: bool = False


@dataclass(frozen=True, slots=True)
class StreamPipelinePlan:
    guards: tuple[object, ...] = ()
    pipes: tuple[object, ...] = ()
    interceptors: tuple[object, ...] = ()
    filters: tuple[object, ...] = ()
    qualified_provider_refs: tuple[tuple[str, ProviderRef], ...] = ()


@dataclass(frozen=True, slots=True)
class StreamHandlerPlan:
    module_id: ModuleId
    controller_ref: ProviderRef
    controller: type[object]
    method_name: str
    handler: Callable[..., object]
    metadata: StreamHandlerMetadata
    parameters: tuple[StreamParameterPlan, ...]
    payload_type: type[object]
    controller_pipeline: StreamPipelinePlan
    method_pipeline: StreamPipelinePlan

    @property
    def handler_id(self) -> str:
        return f"{self.controller.__qualname__}.{self.method_name}"


@dataclass(frozen=True, slots=True)
class StreamHandlerRegistry:
    handlers: tuple[StreamHandlerPlan, ...]
    by_subscription: Mapping[tuple[str, str], StreamHandlerPlan] = field(
        init=False, repr=False
    )

    def __post_init__(self) -> None:
        indexed = {
            (plan.metadata.stream, plan.metadata.consumer_group): plan
            for plan in self.handlers
        }
        if len(indexed) != len(self.handlers):
            raise ValueError("duplicate stream handler subscription")
        object.__setattr__(self, "by_subscription", MappingProxyType(indexed))


__all__ = [
    "StreamHandlerPlan",
    "StreamHandlerRegistry",
    "StreamParameterPlan",
    "StreamPipelinePlan",
]
