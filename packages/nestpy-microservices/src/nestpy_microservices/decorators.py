"""Metadata-only decorators and parameter markers for message handlers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from nestpy import Inject, MetadataKey, metadata

from nestpy_microservices.errors import HandlerCompilationError
from nestpy_microservices.identities import (
    EventIdentity,
    ServiceIdentity,
    validate_alias,
    validate_version,
)


def _validate_source_name(value: str, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise HandlerCompilationError(f"{field} must be a non-empty string")
    return value


class EventDispatchMode(StrEnum):
    """Consumer-owned event delivery topology."""

    SERVICE_POOL = "service_pool"
    SINGLETON = "singleton"
    BROADCAST = "broadcast"


@dataclass(frozen=True, slots=True)
class RpcMetadata:
    """Direct method metadata for one RPC alias."""

    method: str
    schema_version: int


@dataclass(frozen=True, slots=True)
class EventHandlerMetadata:
    """Direct method metadata for one event subscription."""

    source: ServiceIdentity
    event: str
    schema_version: int
    mode: EventDispatchMode
    subscription: str
    reliable: bool

    @property
    def identity(self) -> EventIdentity:
        return EventIdentity(self.source, self.event, self.schema_version)


@dataclass(frozen=True, slots=True)
class Payload:
    """Bind the complete payload or one named payload field."""

    source: str | None = None

    def __post_init__(self) -> None:
        if self.source is not None:
            object.__setattr__(
                self, "source", _validate_source_name(self.source, "payload")
            )


@dataclass(frozen=True, slots=True)
class Context:
    """Bind the transport-neutral message execution context."""


@dataclass(frozen=True, slots=True)
class Headers:
    """Bind the complete immutable safe header mapping."""


@dataclass(frozen=True, slots=True)
class Header:
    """Bind one named safe header."""

    name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _validate_source_name(self.name, "header"))


_RPC_KEY: MetadataKey[RpcMetadata] = MetadataKey("nestpy.microservices.rpc")
_EVENT_KEY: MetadataKey[EventHandlerMetadata] = MetadataKey(
    "nestpy.microservices.event_handler"
)


def rpc(method: str, *, schema_version: int = 1):
    """Decorate one async method with a stable RPC alias."""

    normalized_method = validate_alias(method, "RPC method")
    normalized_version = validate_version(schema_version, "schema_version")
    return metadata(
        _RPC_KEY,
        RpcMetadata(normalized_method, normalized_version),
    )


def event_handler(
    source: ServiceIdentity,
    event: str,
    *,
    schema_version: int,
    mode: EventDispatchMode,
    subscription: str,
    reliable: bool | None = None,
):
    """Decorate one async method with a consumer-owned event subscription."""

    if not isinstance(source, ServiceIdentity):
        raise HandlerCompilationError("event source must be a ServiceIdentity")
    if not isinstance(mode, EventDispatchMode):
        try:
            mode = EventDispatchMode(mode)
        except ValueError as error:
            raise HandlerCompilationError("event mode is invalid") from error
    identity = EventIdentity(source, event, schema_version)
    normalized_subscription = validate_alias(subscription, "subscription")
    if reliable is not None and not isinstance(reliable, bool):
        raise HandlerCompilationError("event reliable must be boolean or None")
    if mode in {EventDispatchMode.SERVICE_POOL, EventDispatchMode.SINGLETON}:
        if reliable is not None:
            raise HandlerCompilationError(f"{mode.value} handlers are always reliable")
        normalized_reliable = True
    else:
        normalized_reliable = False if reliable is None else reliable
    return metadata(
        _EVENT_KEY,
        EventHandlerMetadata(
            source=identity.source,
            event=identity.event,
            schema_version=identity.schema_version,
            mode=mode,
            subscription=normalized_subscription,
            reliable=normalized_reliable,
        ),
    )


def get_rpc_metadata(target: object) -> RpcMetadata | None:
    """Return only metadata declared directly on a method."""

    from nestpy import Reflector

    return Reflector().get_own(_RPC_KEY, target)


def get_event_handler_metadata(target: object) -> EventHandlerMetadata | None:
    """Return only event metadata declared directly on a method."""

    from nestpy import Reflector

    return Reflector().get_own(_EVENT_KEY, target)


__all__ = [
    "Context",
    "EventDispatchMode",
    "EventHandlerMetadata",
    "Header",
    "Headers",
    "Payload",
    "RpcMetadata",
    "event_handler",
    "get_event_handler_metadata",
    "get_rpc_metadata",
    "rpc",
    "Inject",
]
