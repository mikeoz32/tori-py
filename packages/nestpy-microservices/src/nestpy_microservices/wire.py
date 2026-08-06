"""Immutable transport-neutral RPC and event envelopes."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import InitVar, dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Final, cast
from uuid import UUID

import msgspec

from nestpy_microservices.errors import (
    WireDeadlineError,
    WireSizeLimitError,
    WireValidationError,
)
from nestpy_microservices.identities import (
    EventIdentity,
    MessageLimits,
    ReplyRoute,
    RpcTarget,
    ServiceIdentity,
    require_future_deadline,
    require_utc,
    require_uuid,
)

_MISSING_TYPE = type("_Missing", (), {})
RESULT_MISSING: Final[object] = _MISSING_TYPE()


def _freeze_value(
    value: object,
    field_name: str,
    max_depth: int,
    max_collection_items: int,
    depth: int = 0,
) -> object:
    if depth > max_depth:
        raise WireValidationError(f"{field_name} exceeds maximum nesting depth")
    if isinstance(value, float) and not math.isfinite(value):
        raise WireValidationError(f"{field_name} contains a non-finite float")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        if len(value) > max_collection_items:
            raise WireSizeLimitError(f"{field_name} exceeds the collection limit")
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise WireValidationError(
                    f"{field_name} keys must be non-empty strings"
                )
            frozen[key] = _freeze_value(
                item, field_name, max_depth, max_collection_items, depth + 1
            )
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        if len(value) > max_collection_items:
            raise WireSizeLimitError(f"{field_name} exceeds the collection limit")
        return tuple(
            _freeze_value(item, field_name, max_depth, max_collection_items, depth + 1)
            for item in value
        )
    raise WireValidationError(f"{field_name} contains an unsupported value")


def freeze_headers(
    headers: Mapping[str, object] | None,
    limits: MessageLimits | None = None,
) -> Mapping[str, object]:
    """Copy and deeply freeze safe header values."""

    selected_limits = MessageLimits() if limits is None else limits
    source = headers or {}
    if not isinstance(source, Mapping):
        raise WireValidationError("headers must be a mapping")
    if len(source) > selected_limits.max_header_count:
        raise WireValidationError("headers exceed the configured count limit")
    frozen = _freeze_value(
        source,
        "headers",
        selected_limits.max_nesting_depth,
        selected_limits.max_collection_items,
    )
    assert isinstance(frozen, Mapping)
    if (
        len(msgspec.json.encode(_plain_value(frozen)))
        > selected_limits.max_header_bytes
    ):
        raise WireSizeLimitError("headers exceed the configured byte limit")
    return cast(Mapping[str, object], frozen)


def _plain_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class MessageMetadata:
    """Common immutable message metadata shared by envelope constructors."""

    message_id: UUID
    created_at: datetime
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    headers: Mapping[str, object] = field(default_factory=dict)
    limits: InitVar[MessageLimits | None] = None

    def __post_init__(self, limits: MessageLimits | None) -> None:
        require_uuid(self.message_id, "message_id")
        require_utc(self.created_at, "created_at")
        if self.correlation_id is not None:
            require_uuid(self.correlation_id, "correlation_id")
        if self.causation_id is not None:
            require_uuid(self.causation_id, "causation_id")
        object.__setattr__(
            self,
            "headers",
            freeze_headers(self.headers, limits),
        )


@dataclass(frozen=True, slots=True)
class RemoteRpcErrorData:
    """Sanitized, stable error data exchanged by RPC peers."""

    code: str
    message: str
    retryable: bool
    details: Mapping[str, object] = field(default_factory=dict)
    limits: InitVar[MessageLimits | None] = None

    def __post_init__(self, limits: MessageLimits | None) -> None:
        if not self.code or not isinstance(self.code, str):
            raise WireValidationError("remote error code must be a non-empty string")
        if not isinstance(self.message, str) or not self.message:
            raise WireValidationError("remote error message must be non-empty")
        if len(self.message) > 4096:
            raise WireValidationError("remote error message exceeds 4096 characters")
        if not isinstance(self.retryable, bool):
            raise WireValidationError("remote error retryable must be boolean")
        object.__setattr__(self, "details", freeze_headers(self.details, limits))


@dataclass(frozen=True, slots=True)
class RpcRequestEnvelope:
    """Validated RPC request with an application-owned payload."""

    message_id: UUID
    service: ServiceIdentity
    method: str
    schema_version: int
    created_at: datetime
    deadline_at: datetime
    correlation_id: UUID
    causation_id: UUID | None = None
    idempotency_key: str | None = None
    reply_to: ReplyRoute = field(default_factory=ReplyRoute.generate)
    headers: Mapping[str, object] = field(default_factory=dict)
    payload: object = None
    limits: InitVar[MessageLimits | None] = None

    def __post_init__(self, limits: MessageLimits | None) -> None:
        target = RpcTarget(self.service, self.method, self.schema_version)
        require_uuid(self.message_id, "message_id")
        require_uuid(self.correlation_id, "correlation_id")
        if self.causation_id is not None:
            require_uuid(self.causation_id, "causation_id")
        try:
            require_future_deadline(self.created_at, self.deadline_at)
        except WireValidationError as error:
            raise WireDeadlineError(str(error)) from error
        if not isinstance(self.reply_to, ReplyRoute):
            raise WireValidationError("reply_to must be a ReplyRoute")
        if self.idempotency_key is not None and (
            not isinstance(self.idempotency_key, str) or not self.idempotency_key
        ):
            raise WireValidationError("idempotency_key must be a non-empty string")
        object.__setattr__(self, "method", target.method)
        object.__setattr__(self, "headers", freeze_headers(self.headers, limits))

    @property
    def kind(self) -> str:
        return "rpc_request"


@dataclass(frozen=True, slots=True)
class RpcResponseEnvelope:
    """Validated RPC response containing exactly one result or error."""

    message_id: UUID
    correlation_id: UUID
    completed_at: datetime
    result: object = RESULT_MISSING
    error: RemoteRpcErrorData | None = None
    limits: InitVar[MessageLimits | None] = None

    def __post_init__(self, limits: MessageLimits | None) -> None:
        require_uuid(self.message_id, "message_id")
        require_uuid(self.correlation_id, "correlation_id")
        require_utc(self.completed_at, "completed_at")
        has_result = self.result is not RESULT_MISSING
        has_error = self.error is not None
        if has_result == has_error:
            raise WireValidationError(
                "RPC response must contain exactly one result/error"
            )
        if has_error and not isinstance(self.error, RemoteRpcErrorData):
            raise WireValidationError("error must be RemoteRpcErrorData")

    @property
    def kind(self) -> str:
        return "rpc_response"


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """Validated one-way event publication envelope."""

    message_id: UUID
    source: ServiceIdentity
    event: str
    schema_version: int
    occurred_at: datetime
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    headers: Mapping[str, object] = field(default_factory=dict)
    payload: object = None
    limits: InitVar[MessageLimits | None] = None

    def __post_init__(self, limits: MessageLimits | None) -> None:
        identity = EventIdentity(self.source, self.event, self.schema_version)
        require_uuid(self.message_id, "message_id")
        require_utc(self.occurred_at, "occurred_at")
        if self.correlation_id is not None:
            require_uuid(self.correlation_id, "correlation_id")
        if self.causation_id is not None:
            require_uuid(self.causation_id, "causation_id")
        object.__setattr__(self, "event", identity.event)
        object.__setattr__(self, "headers", freeze_headers(self.headers, limits))

    @property
    def kind(self) -> str:
        return "event"


__all__ = [
    "EventEnvelope",
    "MessageMetadata",
    "RESULT_MISSING",
    "RemoteRpcErrorData",
    "RpcRequestEnvelope",
    "RpcResponseEnvelope",
    "freeze_headers",
]
