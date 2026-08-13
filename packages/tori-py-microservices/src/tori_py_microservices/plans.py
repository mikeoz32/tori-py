"""Immutable compiled message handler views."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from tori_py import ModuleId, ProviderRef, Token

from tori_py_microservices.decorators import (
    EventDispatchMode,
    EventHandlerMetadata,
    RpcMetadata,
)
from tori_py_microservices.identities import EventIdentity, RpcTarget, ServiceIdentity


@dataclass(frozen=True, slots=True)
class MessageParameterPlan:
    """One compiled marker binding for a message handler parameter."""

    name: str
    annotation: object
    kind: str
    source: str | None
    token: Token | None
    provider_ref: ProviderRef | None
    default: object
    has_default: bool


@dataclass(frozen=True, slots=True)
class PipelinePlan:
    """Direct controller/method pipeline metadata captured in declaration order."""

    middleware: tuple[object, ...] = ()
    guards: tuple[object, ...] = ()
    pipes: tuple[object, ...] = ()
    interceptors: tuple[object, ...] = ()
    filters: tuple[object, ...] = ()
    qualified_provider_refs: tuple[tuple[str, ProviderRef], ...] = ()


@dataclass(frozen=True, slots=True)
class RpcHandlerPlan:
    """Compiled RPC handler entry point."""

    module_id: ModuleId
    controller_ref: ProviderRef
    controller: type[object]
    method_name: str
    handler: Callable[..., object]
    metadata: RpcMetadata
    parameters: tuple[MessageParameterPlan, ...]
    return_annotation: object
    controller_pipeline: PipelinePlan
    method_pipeline: PipelinePlan

    @property
    def method(self) -> str:
        return self.metadata.method

    @property
    def schema_version(self) -> int:
        return self.metadata.schema_version

    def target(self, service: ServiceIdentity) -> RpcTarget:
        return RpcTarget(service, self.method, self.schema_version)


@dataclass(frozen=True, slots=True)
class EventHandlerPlan:
    """Compiled event consumer entry point."""

    module_id: ModuleId
    controller_ref: ProviderRef
    controller: type[object]
    method_name: str
    handler: Callable[..., object]
    metadata: EventHandlerMetadata
    parameters: tuple[MessageParameterPlan, ...]
    return_annotation: object
    controller_pipeline: PipelinePlan
    method_pipeline: PipelinePlan

    @property
    def identity(self) -> EventIdentity:
        return self.metadata.identity

    @property
    def mode(self) -> EventDispatchMode:
        return self.metadata.mode

    @property
    def subscription(self) -> str:
        return self.metadata.subscription


@dataclass(frozen=True, slots=True)
class ServiceHandlerRegistry:
    """Immutable application-wide message handler registry."""

    rpc_handlers: tuple[RpcHandlerPlan, ...]
    event_handlers: tuple[EventHandlerPlan, ...]
    rpc_by_target: Mapping[tuple[str, int], RpcHandlerPlan] = field(
        init=False, repr=False
    )
    rpc_methods: frozenset[str] = field(init=False, repr=False)
    event_by_subscription: Mapping[
        tuple[EventIdentity, EventDispatchMode, str], EventHandlerPlan
    ] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        rpc_by_target = {
            (plan.method, plan.schema_version): plan for plan in self.rpc_handlers
        }
        rpc_methods = {plan.method for plan in self.rpc_handlers}
        event_by_subscription = {
            (
                plan.identity,
                plan.mode,
                plan.subscription,
            ): plan
            for plan in self.event_handlers
        }
        if len(rpc_by_target) != len(self.rpc_handlers):
            raise ValueError("duplicate RPC target in handler registry")
        if len(rpc_methods) != len(self.rpc_handlers):
            raise ValueError("duplicate RPC method alias in handler registry")
        if len(event_by_subscription) != len(self.event_handlers):
            raise ValueError("duplicate event subscription in handler registry")

        object.__setattr__(self, "rpc_by_target", MappingProxyType(rpc_by_target))
        object.__setattr__(
            self,
            "rpc_methods",
            frozenset(rpc_methods),
        )
        object.__setattr__(
            self,
            "event_by_subscription",
            MappingProxyType(event_by_subscription),
        )


def is_explicit_none(annotation: object) -> bool:
    """Return whether a resolved annotation explicitly means ``None``."""

    return annotation is None or annotation is type(None)


__all__ = [
    "EventHandlerPlan",
    "MessageParameterPlan",
    "PipelinePlan",
    "RpcHandlerPlan",
    "ServiceHandlerRegistry",
    "is_explicit_none",
]
