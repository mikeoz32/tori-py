"""Immutable identities and bounded values used by the wire protocol."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from tori_py_microservices.errors import IdentityValidationError, WireValidationError

_ALIAS_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
_REPLY_ROUTE_PATTERN = re.compile(r"^reply\.[0-9a-f]{32}$")
_MAX_AMQP_SHORT_STRING_BYTES = 255


def _validate_alias(value: str, field: str) -> str:
    if not isinstance(value, str) or not _ALIAS_PATTERN.fullmatch(value):
        raise IdentityValidationError(f"{field} must match [a-z][a-z0-9_-]{{0,62}}")
    return value


def _validate_version(value: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise IdentityValidationError(f"{field} must be a positive integer")
    return value


def validate_alias(value: str, field: str = "alias") -> str:
    """Validate one stable lowercase ASCII topic segment."""

    return _validate_alias(value, field)


def validate_version(value: int, field: str = "version") -> int:
    """Validate one positive contract or schema version."""

    return _validate_version(value, field)


def _validate_composed_name(value: str, field: str) -> str:
    if len(value.encode("utf-8")) > _MAX_AMQP_SHORT_STRING_BYTES:
        raise IdentityValidationError(
            f"{field} exceeds the RabbitMQ 255-byte short-string limit"
        )
    return value


@dataclass(frozen=True, slots=True)
class ServiceIdentity:
    """Stable namespace, service, and service contract identity."""

    namespace: str
    name: str
    contract_version: int

    def __post_init__(self) -> None:
        _validate_alias(self.namespace, "namespace")
        _validate_alias(self.name, "name")
        _validate_version(self.contract_version, "contract_version")
        _validate_composed_name(self.label, "service label")

    @property
    def label(self) -> str:
        return f"{self.namespace}.{self.name}.v{self.contract_version}"


@dataclass(frozen=True, slots=True)
class RpcTarget:
    """One RPC method and request schema within a target service contract."""

    service: ServiceIdentity
    method: str
    schema_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.service, ServiceIdentity):
            raise IdentityValidationError("service must be a ServiceIdentity")
        _validate_alias(self.method, "method")
        _validate_version(self.schema_version, "schema_version")
        _validate_composed_name(self.routing_key, "RPC routing key")

    @property
    def routing_key(self) -> str:
        return f"{self.service.label}.{self.method}"


@dataclass(frozen=True, slots=True)
class EventIdentity:
    """One event alias and payload schema from a source service."""

    source: ServiceIdentity
    event: str
    schema_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.source, ServiceIdentity):
            raise IdentityValidationError("source must be a ServiceIdentity")
        _validate_alias(self.event, "event")
        _validate_version(self.schema_version, "schema_version")
        _validate_composed_name(self.exchange_name, "event exchange")
        _validate_composed_name(self.routing_key, "event routing key")

    @property
    def exchange_name(self) -> str:
        return f"tori_py.events.{self.source.label}"

    @property
    def routing_key(self) -> str:
        return f"{self.event}.v{self.schema_version}"


@dataclass(frozen=True, slots=True)
class ReplyRoute:
    """Generated reply routing key accepted by the RPC responder."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _REPLY_ROUTE_PATTERN.fullmatch(
            self.value
        ):
            raise WireValidationError(
                "reply route must match reply.<32 lowercase hexadecimal characters>"
            )

    @classmethod
    def generate(cls) -> ReplyRoute:
        return cls(f"reply.{secrets.token_hex(16)}")


@dataclass(frozen=True, slots=True)
class MessageLimits:
    """Shared finite limits applied before expensive wire decoding."""

    max_envelope_bytes: int = 1024 * 1024
    max_header_count: int = 64
    max_header_bytes: int = 64 * 1024
    max_nesting_depth: int = 64
    max_collection_items: int = 10_000

    def __post_init__(self) -> None:
        for field in (
            "max_envelope_bytes",
            "max_header_count",
            "max_header_bytes",
            "max_nesting_depth",
            "max_collection_items",
        ):
            value = getattr(self, field)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise WireValidationError(f"{field} must be a positive integer")


def require_utc(value: datetime, field: str = "timestamp") -> datetime:
    """Validate a timezone-aware UTC timestamp without silently converting it."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise WireValidationError(f"{field} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise WireValidationError(f"{field} must use UTC")
    return value


def require_uuid(value: UUID, field: str = "id") -> UUID:
    """Validate a UUID value used as a wire identifier."""

    if not isinstance(value, UUID):
        raise WireValidationError(f"{field} must be a UUID")
    return value


def require_future_deadline(
    created_at: datetime, deadline_at: datetime
) -> tuple[datetime, datetime]:
    """Validate the creation/deadline relationship used by RPC requests."""

    require_utc(created_at, "created_at")
    require_utc(deadline_at, "deadline_at")
    if deadline_at <= created_at:
        raise WireValidationError("deadline_at must be later than created_at")
    return created_at, deadline_at


def utc_now() -> datetime:
    """Return an aware UTC timestamp for envelope construction."""

    return datetime.now(UTC)


__all__ = [
    "EventIdentity",
    "MessageLimits",
    "ReplyRoute",
    "RpcTarget",
    "ServiceIdentity",
    "require_future_deadline",
    "require_uuid",
    "require_utc",
    "validate_alias",
    "validate_version",
    "utc_now",
]
