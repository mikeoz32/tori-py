"""Immutable transport-neutral message execution contexts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from tori_py import ModuleId, ScopedResolver

from tori_py_microservices.identities import (
    MessageLimits,
    require_utc,
    require_uuid,
    utc_now,
)
from tori_py_microservices.wire import freeze_headers


def module_label(module_id: ModuleId) -> str:
    """Return the stable diagnostic label for a qualified module identity."""

    label = module_id.module.__qualname__
    return label if module_id.key is None else f"{label}[{module_id.key}]"


@dataclass(frozen=True, slots=True)
class MessageContext:
    """Common immutable context passed to message pipeline components."""

    application: str
    module_identity: ModuleId
    handler_id: str
    correlation_id: UUID | None
    scope_resolver: ScopedResolver
    message_metadata: Mapping[str, object]
    message_id: UUID | None = None
    causation_id: UUID | None = None
    received_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    attempt: int = 1
    redelivered: bool = False
    native_value: object | None = None
    limits: MessageLimits = field(default_factory=MessageLimits)

    def __post_init__(self) -> None:
        if not isinstance(self.application, str) or not self.application:
            raise ValueError("application must be a non-empty string")
        if not isinstance(self.module_identity, ModuleId):
            raise ValueError("module_identity must be a ModuleId")
        if not isinstance(self.handler_id, str) or not self.handler_id:
            raise ValueError("handler_id must be a non-empty string")
        if self.message_id is not None:
            require_uuid(self.message_id, "message_id")
        if self.correlation_id is not None:
            require_uuid(self.correlation_id, "correlation_id")
        if self.causation_id is not None:
            require_uuid(self.causation_id, "causation_id")
        if not isinstance(self.attempt, int) or self.attempt <= 0:
            raise ValueError("attempt must be a positive integer")
        if not isinstance(self.redelivered, bool):
            raise ValueError("redelivered must be boolean")
        require_utc(self.received_at, "received_at")
        if self.expires_at is not None:
            require_utc(self.expires_at, "expires_at")
        object.__setattr__(
            self,
            "message_metadata",
            freeze_headers(self.message_metadata, self.limits),
        )

    @property
    def application_id(self) -> str:
        return self.application

    @property
    def module_id(self) -> str | None:
        return module_label(self.module_identity)

    @property
    def route_id(self) -> str | None:
        return self.handler_id

    @property
    def request_id(self) -> str | None:
        return None if self.correlation_id is None else str(self.correlation_id)

    @property
    def resolver(self) -> ScopedResolver:
        return self.scope_resolver

    @property
    def metadata(self) -> Mapping[str, object]:
        return self.message_metadata

    @property
    def execution_kind(self) -> str:
        return "message"

    def unwrap(self) -> object:
        """Return the opaque native transport value without settlement APIs."""

        return self.native_value


@dataclass(frozen=True, slots=True)
class RpcContext(MessageContext):
    """Immutable context passed to RPC guards, pipes, and interceptors."""

    @property
    def execution_kind(self) -> str:
        return "rpc"


@dataclass(frozen=True, slots=True)
class EventContext(MessageContext):
    """Immutable context passed to event guards, pipes, and interceptors."""

    @property
    def execution_kind(self) -> str:
        return "event"


__all__ = ["EventContext", "MessageContext", "RpcContext", "module_label"]
