"""Deterministic RabbitMQ declaration compiler without an aio-pika import."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from nestpy_microservices.identities import ReplyRoute, ServiceIdentity
from nestpy_microservices.transport import EventSubscription

_MAX_NAME_BYTES = 255
_MAX_EXCHANGE_NAME_BYTES = 127
_DEAD_LETTER_EXCHANGE = "nestpy.dead-letter"
_DEFAULT_DELIVERY_LIMIT = 5
_DEFAULT_RETRY_DELAY_MS = 1_000
_RETRY_QUEUE_LIMIT = 10_000
_RELIABLE_BROADCAST_EXPIRES_MS = 604_800_000
_RELIABLE_BROADCAST_TTL_MS = 86_400_000


@dataclass(frozen=True, slots=True)
class ExchangeDeclaration:
    name: str
    kind: Literal["topic"] = "topic"
    durable: bool = True
    arguments: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class QueueDeclaration:
    name: str
    durable: bool
    exclusive: bool
    auto_delete: bool
    arguments: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class BindingDeclaration:
    exchange: str
    queue: str
    routing_key: str
    arguments: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class RabbitMqTopology:
    exchanges: tuple[ExchangeDeclaration, ...] = ()
    queues: tuple[QueueDeclaration, ...] = ()
    bindings: tuple[BindingDeclaration, ...] = ()


def compile_rpc_topology(
    service: ServiceIdentity,
    *,
    exchange: str = "nestpy.rpc",
    retry_delay_ms: int = _DEFAULT_RETRY_DELAY_MS,
    delivery_limit: int = _DEFAULT_DELIVERY_LIMIT,
) -> RabbitMqTopology:
    _bounded_exchange(exchange, "RPC exchange")
    queue = f"nestpy.rpc.{service.label}"
    binding = f"{service.label}.*"
    _bounded(queue, "RPC queue")
    _bounded(binding, "RPC binding")
    return _durable_topology(
        exchange=exchange,
        queue_name=queue,
        routing_key=binding,
        queue_arguments=(("x-queue-type", "quorum"),),
        retry_delay_ms=retry_delay_ms,
        delivery_limit=delivery_limit,
    )


def compile_event_topology(
    subscription: EventSubscription,
    *,
    retry_delay_ms: int = _DEFAULT_RETRY_DELAY_MS,
    delivery_limit: int = _DEFAULT_DELIVERY_LIMIT,
) -> RabbitMqTopology:
    identity = subscription.identity
    prefix = (
        f"nestpy.event.{identity.source.label}.{identity.event}."
        f"v{identity.schema_version}"
    )
    if subscription.mode == "service_pool":
        assert subscription.destination is not None
        queue_name = (
            f"{prefix}--pool.{subscription.destination.label}."
            f"{subscription.subscription}"
        )
        durable_arguments = (("x-queue-type", "quorum"),)
    elif subscription.mode == "singleton":
        queue_name = f"{prefix}--singleton.{subscription.subscription}"
        durable_arguments = (("x-queue-type", "quorum"),)
    else:
        assert subscription.destination is not None
        assert subscription.instance_id is not None
        queue_name = (
            f"{prefix}--broadcast.{subscription.destination.label}."
            f"{subscription.subscription}.{subscription.instance_id}"
        )
        if subscription.reliable is True:
            durable_arguments = (
                ("x-queue-type", "classic"),
                ("x-expires", _RELIABLE_BROADCAST_EXPIRES_MS),
                ("x-message-ttl", _RELIABLE_BROADCAST_TTL_MS),
            )
        else:
            queue = QueueDeclaration(
                queue_name,
                durable=False,
                exclusive=True,
                auto_delete=True,
                arguments=(("x-queue-type", "classic"),),
            )
    _bounded_exchange(identity.exchange_name, "event exchange")
    _bounded(identity.routing_key, "event routing key")
    _bounded(queue_name, "event queue")
    if subscription.reliable is True:
        return _durable_topology(
            exchange=identity.exchange_name,
            queue_name=queue_name,
            routing_key=identity.routing_key,
            queue_arguments=durable_arguments,
            retry_delay_ms=retry_delay_ms,
            delivery_limit=delivery_limit,
        )
    return RabbitMqTopology(
        exchanges=(ExchangeDeclaration(identity.exchange_name),),
        queues=(queue,),
        bindings=(
            BindingDeclaration(
                identity.exchange_name,
                queue_name,
                identity.routing_key,
            ),
        ),
    )


def compile_reply_topology(
    route: str,
    *,
    exchange: str = "nestpy.rpc",
    expires_ms: int = 300_000,
) -> RabbitMqTopology:
    route = ReplyRoute(route).value
    if (
        not isinstance(expires_ms, int)
        or isinstance(expires_ms, bool)
        or expires_ms <= 0
    ):
        raise ValueError("reply queue expiry must be a positive integer")
    _bounded_exchange(exchange, "RPC exchange")
    _bounded(route, "reply queue")
    return RabbitMqTopology(
        exchanges=(ExchangeDeclaration(exchange),),
        queues=(
            QueueDeclaration(
                route,
                durable=False,
                exclusive=True,
                auto_delete=True,
                arguments=(("x-expires", expires_ms),),
            ),
        ),
        bindings=(BindingDeclaration(exchange, route, route),),
    )


def event_exchange_topology(exchange: str) -> RabbitMqTopology:
    """Return the producer-owned durable topic exchange declaration."""

    _bounded_exchange(exchange, "event exchange")
    return RabbitMqTopology(exchanges=(ExchangeDeclaration(exchange),))


def _durable_topology(
    *,
    exchange: str,
    queue_name: str,
    routing_key: str,
    queue_arguments: tuple[tuple[str, object], ...],
    retry_delay_ms: int,
    delivery_limit: int,
) -> RabbitMqTopology:
    _positive(retry_delay_ms, "retry delay")
    _positive(delivery_limit, "delivery limit")
    dead_queue = f"{queue_name}.dead-letter"
    retry_queue = f"{queue_name}.retry"
    retry_exchange = retry_exchange_name(queue_name)
    _bounded(dead_queue, "dead-letter queue")
    _bounded(retry_queue, "retry queue")
    delivery_limit_arguments = (
        (("x-delivery-limit", delivery_limit),)
        if ("x-queue-type", "quorum") in queue_arguments
        else ()
    )
    arguments = (
        *queue_arguments,
        *delivery_limit_arguments,
        ("x-dead-letter-exchange", _DEAD_LETTER_EXCHANGE),
        ("x-dead-letter-routing-key", queue_name),
    )
    return RabbitMqTopology(
        exchanges=(
            ExchangeDeclaration(exchange),
            ExchangeDeclaration(_DEAD_LETTER_EXCHANGE),
            ExchangeDeclaration(retry_exchange),
        ),
        queues=(
            QueueDeclaration(queue_name, True, False, False, arguments),
            QueueDeclaration(
                dead_queue,
                True,
                False,
                False,
                (("x-queue-type", "quorum"),),
            ),
            QueueDeclaration(
                retry_queue,
                True,
                False,
                False,
                (
                    ("x-queue-type", "classic"),
                    ("x-message-ttl", retry_delay_ms),
                    ("x-dead-letter-exchange", exchange),
                    ("x-max-length", _RETRY_QUEUE_LIMIT),
                    ("x-overflow", "reject-publish"),
                ),
            ),
        ),
        bindings=(
            BindingDeclaration(exchange, queue_name, routing_key),
            BindingDeclaration(
                _DEAD_LETTER_EXCHANGE,
                dead_queue,
                queue_name,
            ),
            BindingDeclaration(retry_exchange, retry_queue, routing_key),
        ),
    )


def retry_exchange_name(queue_name: str) -> str:
    """Return the dedicated retry exchange for one primary queue."""

    value = f"{queue_name}.retry"
    if len(value.encode("utf-8")) <= _MAX_EXCHANGE_NAME_BYTES:
        return value
    digest = sha256(queue_name.encode("utf-8")).hexdigest()
    return f"nestpy.retry.{digest}"


def merge_topologies(*topologies: RabbitMqTopology) -> RabbitMqTopology:
    exchanges: dict[str, ExchangeDeclaration] = {}
    queues: dict[str, QueueDeclaration] = {}
    bindings: dict[tuple[str, str, str], BindingDeclaration] = {}
    for topology in topologies:
        for exchange in topology.exchanges:
            _merge(exchanges, exchange.name, exchange, "exchange")
        for queue in topology.queues:
            _merge(queues, queue.name, queue, "queue")
        for binding in topology.bindings:
            key = (binding.exchange, binding.queue, binding.routing_key)
            existing = bindings.get(key)
            if existing is not None and existing != binding:
                raise ValueError(f"conflicting RabbitMQ binding declaration {key!r}")
            bindings[key] = binding
    return RabbitMqTopology(
        exchanges=tuple(exchanges.values()),
        queues=tuple(queues.values()),
        bindings=tuple(bindings.values()),
    )


def _merge[T](
    values: dict[str, T],
    name: str,
    value: T,
    kind: str,
) -> None:
    existing = values.get(name)
    if existing is not None and existing != value:
        raise ValueError(f"conflicting RabbitMQ {kind} declaration {name!r}")
    values[name] = value


def _bounded(value: str, field_name: str) -> None:
    if len(value.encode("utf-8")) > _MAX_NAME_BYTES:
        raise ValueError(f"{field_name} exceeds RabbitMQ's 255-byte name limit")


def _bounded_exchange(value: str, field_name: str) -> None:
    if len(value.encode("utf-8")) > _MAX_EXCHANGE_NAME_BYTES:
        raise ValueError(f"{field_name} exceeds RabbitMQ's 127-byte exchange limit")


def _positive(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


__all__ = [
    "BindingDeclaration",
    "ExchangeDeclaration",
    "QueueDeclaration",
    "RabbitMqTopology",
    "compile_event_topology",
    "compile_reply_topology",
    "compile_rpc_topology",
    "event_exchange_topology",
    "merge_topologies",
    "retry_exchange_name",
]
