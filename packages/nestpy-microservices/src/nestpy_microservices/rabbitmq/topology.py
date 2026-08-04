"""Deterministic RabbitMQ declaration compiler without an aio-pika import."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from nestpy_microservices.identities import ReplyRoute, ServiceIdentity
from nestpy_microservices.transport import EventSubscription

_MAX_NAME_BYTES = 255


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
    service: ServiceIdentity, *, exchange: str = "nestpy.rpc"
) -> RabbitMqTopology:
    _bounded(exchange, "RPC exchange")
    queue = f"nestpy.rpc.{service.label}"
    binding = f"{service.label}.*"
    _bounded(queue, "RPC queue")
    _bounded(binding, "RPC binding")
    return RabbitMqTopology(
        exchanges=(ExchangeDeclaration(exchange),),
        queues=(
            QueueDeclaration(
                queue,
                durable=True,
                exclusive=False,
                auto_delete=False,
                arguments=(("x-queue-type", "quorum"),),
            ),
        ),
        bindings=(BindingDeclaration(exchange, queue, binding),),
    )


def compile_event_topology(
    subscription: EventSubscription,
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
        queue = QueueDeclaration(
            queue_name,
            durable=True,
            exclusive=False,
            auto_delete=False,
            arguments=(("x-queue-type", "quorum"),),
        )
    elif subscription.mode == "singleton":
        queue_name = f"{prefix}--singleton.{subscription.subscription}"
        queue = QueueDeclaration(
            queue_name,
            durable=True,
            exclusive=False,
            auto_delete=False,
            arguments=(("x-queue-type", "quorum"),),
        )
    else:
        assert subscription.destination is not None
        assert subscription.instance_id is not None
        queue_name = (
            f"{prefix}--broadcast.{subscription.destination.label}."
            f"{subscription.subscription}.{subscription.instance_id}"
        )
        queue = QueueDeclaration(
            queue_name,
            durable=bool(subscription.reliable),
            exclusive=True,
            auto_delete=not subscription.reliable,
        )
    _bounded(identity.exchange_name, "event exchange")
    _bounded(identity.routing_key, "event routing key")
    _bounded(queue_name, "event queue")
    return RabbitMqTopology(
        exchanges=(ExchangeDeclaration(identity.exchange_name),),
        queues=(queue,),
        bindings=(
            BindingDeclaration(
                identity.exchange_name, queue_name, identity.routing_key
            ),
        ),
    )


def compile_reply_topology(route: str) -> RabbitMqTopology:
    route = ReplyRoute(route).value
    _bounded(route, "reply queue")
    return RabbitMqTopology(
        exchanges=(ExchangeDeclaration("nestpy.rpc"),),
        queues=(
            QueueDeclaration(
                route,
                durable=False,
                exclusive=True,
                auto_delete=True,
            ),
        ),
        bindings=(BindingDeclaration("nestpy.rpc", route, route),),
    )


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


__all__ = [
    "BindingDeclaration",
    "ExchangeDeclaration",
    "QueueDeclaration",
    "RabbitMqTopology",
    "compile_event_topology",
    "compile_reply_topology",
    "compile_rpc_topology",
    "merge_topologies",
]
