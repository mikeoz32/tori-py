"""Transport-neutral contracts shared by broker adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID, uuid4

from tori_py_microservices.identities import (
    EventIdentity,
    ReplyRoute,
    RpcTarget,
    ServiceIdentity,
    require_utc,
    require_uuid,
    validate_alias,
)
from tori_py_microservices.invocation import (
    InvocationCompletion,
    SettlementRecommendation,
)
from tori_py_microservices.wire import freeze_headers

if TYPE_CHECKING:
    from tori_py_microservices.options import MicroservicesOptions

_UNSET_RELIABILITY = object()


class TransportStatus(StrEnum):
    """Lifecycle states observable by transport users."""

    CREATED = "created"
    PREPARED = "prepared"
    RUNNING = "running"
    QUIESCING = "quiescing"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class EncodedDelivery:
    """One encoded broker delivery before framework decoding."""

    message_id: UUID
    routing_key: str
    body: bytes
    headers: Mapping[str, object]
    received_at: datetime
    attempt: int = 1
    redelivered: bool = False
    correlation_id: UUID | None = None
    reply_to: ReplyRoute | None = None
    native: object | None = None
    expires_at: datetime | None = None
    subscription: EventSubscription | None = None

    def __post_init__(self) -> None:
        require_uuid(self.message_id, "message_id")
        if not isinstance(self.routing_key, str) or not self.routing_key:
            raise ValueError("routing_key must be a non-empty string")
        if not isinstance(self.body, bytes):
            raise TypeError("body must be bytes")
        require_utc(self.received_at, "received_at")
        if not isinstance(self.attempt, int) or isinstance(self.attempt, bool):
            raise ValueError("attempt must be a positive integer")
        if self.attempt <= 0:
            raise ValueError("attempt must be a positive integer")
        if not isinstance(self.redelivered, bool):
            raise ValueError("redelivered must be boolean")
        if self.correlation_id is not None:
            require_uuid(self.correlation_id, "correlation_id")
        if self.expires_at is not None:
            require_utc(self.expires_at, "expires_at")
        if self.subscription is not None and not isinstance(
            self.subscription, EventSubscription
        ):
            raise TypeError("subscription must be an EventSubscription")
        object.__setattr__(self, "headers", freeze_headers(self.headers))


@dataclass(frozen=True, slots=True)
class ReplyProtocolFailure:
    """Trusted reply correlation whose remaining transport metadata is invalid."""

    correlation_id: UUID
    reason: str

    def __post_init__(self) -> None:
        require_uuid(self.correlation_id, "correlation_id")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("reason must be a non-empty string")


@dataclass(frozen=True, slots=True)
class Publication:
    """One outbound encoded publication submitted to a transport."""

    message_id: UUID
    routing_key: str
    body: bytes
    headers: Mapping[str, object]
    mandatory: bool = False
    correlation_id: UUID | None = None
    reply_to: ReplyRoute | None = None
    native: object | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        require_uuid(self.message_id, "message_id")
        if not isinstance(self.routing_key, str) or not self.routing_key:
            raise ValueError("routing_key must be a non-empty string")
        if not isinstance(self.body, bytes):
            raise TypeError("body must be bytes")
        if not isinstance(self.mandatory, bool):
            raise ValueError("mandatory must be boolean")
        if self.correlation_id is not None:
            require_uuid(self.correlation_id, "correlation_id")
        if self.expires_at is not None:
            require_utc(self.expires_at, "expires_at")
        object.__setattr__(self, "headers", freeze_headers(self.headers))


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    """Broker acceptance, distinct from handler execution."""

    message_id: UUID
    accepted_at: datetime
    routed: bool

    def __post_init__(self) -> None:
        require_uuid(self.message_id, "message_id")
        require_utc(self.accepted_at, "accepted_at")
        if not isinstance(self.routed, bool):
            raise ValueError("routed must be boolean")


@dataclass(frozen=True, slots=True)
class EventSubscription:
    """Explicit event route information supplied to a transport."""

    identity: EventIdentity
    mode: str
    subscription: str
    destination: ServiceIdentity | None = None
    instance_id: str | None = None
    reliable: bool | object = _UNSET_RELIABILITY

    def __post_init__(self) -> None:
        if not isinstance(self.identity, EventIdentity):
            raise TypeError("identity must be an EventIdentity")
        if self.mode not in {"service_pool", "singleton", "broadcast"}:
            raise ValueError("unsupported event dispatch mode")
        validate_alias(self.subscription, "subscription")
        if self.destination is not None and not isinstance(
            self.destination, ServiceIdentity
        ):
            raise TypeError("destination must be a ServiceIdentity")
        if self.instance_id is not None:
            validate_alias(self.instance_id, "instance_id")
        reliability_unset = self.reliable is _UNSET_RELIABILITY
        if reliability_unset:
            object.__setattr__(
                self, "reliable", self.mode in {"service_pool", "singleton"}
            )
        if not isinstance(self.reliable, bool):
            raise ValueError("reliable must be boolean")
        if self.mode in {"service_pool", "singleton"} and not self.reliable:
            raise ValueError(f"{self.mode} subscriptions must be reliable")
        if self.mode == "service_pool" and self.destination is None:
            raise ValueError("service_pool subscriptions require a destination")
        if self.mode == "broadcast" and self.reliable and self.instance_id is None:
            raise ValueError("reliable broadcast subscriptions require an instance_id")
        if self.mode == "broadcast" and self.destination is None:
            raise ValueError("broadcast subscriptions require a destination")
        if self.mode == "broadcast" and self.instance_id is None:
            object.__setattr__(self, "instance_id", f"instance-{uuid4().hex}")


@dataclass(frozen=True, slots=True)
class TransportStatusEvent:
    """One transport lifecycle transition."""

    status: TransportStatus
    changed_at: datetime
    detail: str = ""
    generation: int = 0

    def __post_init__(self) -> None:
        require_utc(self.changed_at, "changed_at")
        if (
            not isinstance(self.generation, int)
            or isinstance(self.generation, bool)
            or self.generation < 0
        ):
            raise ValueError("generation must be a non-negative integer")


DeliveryDispatcher = Callable[
    [EncodedDelivery], Awaitable[InvocationCompletion | SettlementRecommendation]
]


@runtime_checkable
class ServerTransport(Protocol):
    """Inbound transport boundary owned by a service runtime."""

    @property
    def status(self) -> TransportStatus: ...

    async def prepare(
        self,
        *,
        rpc_methods: Iterable[str] = (),
        subscriptions: Iterable[EventSubscription] = (),
    ) -> None: ...

    async def start(self, dispatcher: DeliveryDispatcher) -> None: ...

    async def settle(
        self, delivery: EncodedDelivery, outcome: SettlementRecommendation
    ) -> None: ...

    async def publish_reply(self, publication: Publication) -> PublicationReceipt: ...

    async def stop_intake(self) -> None: ...

    async def close(self) -> None: ...

    def statuses(self) -> AsyncIterator[TransportStatusEvent]: ...

    def unwrap(self) -> object: ...


@runtime_checkable
class ClientTransport(Protocol):
    """Outbound transport boundary owned by a service cluster client."""

    @property
    def status(self) -> TransportStatus: ...

    @property
    def generation(self) -> int: ...

    @property
    def reply_to(self) -> ReplyRoute: ...

    async def start(self, *, receive_replies: bool = True) -> None: ...

    async def publish_rpc(
        self, target: RpcTarget, publication: Publication
    ) -> PublicationReceipt: ...

    async def publish_event(
        self, identity: EventIdentity, publication: Publication
    ) -> PublicationReceipt: ...

    def cancel_publication_after_reply(self, correlation_id: UUID) -> None: ...

    def replies(
        self,
    ) -> AsyncIterator[EncodedDelivery | ReplyProtocolFailure]: ...

    async def close(self) -> None: ...

    def cancel_pending(self, correlation_id: UUID) -> None: ...

    def statuses(self) -> AsyncIterator[TransportStatusEvent]: ...

    def unwrap(self) -> object: ...


@runtime_checkable
class ServerTransportFactory(Protocol):
    """Create one server transport without opening native resources."""

    def create(
        self, identity: ServiceIdentity, options: MicroservicesOptions
    ) -> ServerTransport: ...


@runtime_checkable
class ClientTransportFactory(Protocol):
    """Create one client transport without opening native resources."""

    def create(self) -> ClientTransport: ...


@runtime_checkable
class KeyedTransportFactoryReference(Protocol):
    """Reference exact adapter-owned factory providers by one root key."""

    @property
    def key(self) -> str: ...

    @property
    def server_factory_token(self) -> type[object] | str: ...

    @property
    def client_factory_token(self) -> type[object] | str: ...


__all__ = [
    "ClientTransport",
    "ClientTransportFactory",
    "DeliveryDispatcher",
    "EncodedDelivery",
    "EventSubscription",
    "KeyedTransportFactoryReference",
    "Publication",
    "PublicationReceipt",
    "ReplyProtocolFailure",
    "ServerTransport",
    "ServerTransportFactory",
    "TransportStatus",
    "TransportStatusEvent",
]
