"""Lazy RabbitMQ integration facade."""

from nestpy_microservices.rabbitmq.dependencies import require_aio_pika
from nestpy_microservices.rabbitmq.module import (
    RabbitMqModule,
    RabbitMqRoot,
    RabbitMqTransport,
)
from nestpy_microservices.rabbitmq.options import RabbitMqOptions
from nestpy_microservices.rabbitmq.topology import (
    BindingDeclaration,
    ExchangeDeclaration,
    QueueDeclaration,
    RabbitMqTopology,
    compile_event_topology,
    compile_reply_topology,
    compile_rpc_topology,
    merge_topologies,
)

__all__ = [
    "BindingDeclaration",
    "ExchangeDeclaration",
    "QueueDeclaration",
    "RabbitMqModule",
    "RabbitMqOptions",
    "RabbitMqRoot",
    "RabbitMqTopology",
    "RabbitMqTransport",
    "compile_event_topology",
    "compile_reply_topology",
    "compile_rpc_topology",
    "merge_topologies",
    "require_aio_pika",
]
