"""Lazy RabbitMQ integration facade."""

from nestpy_microservices.rabbitmq.client import RabbitMqClientTransport
from nestpy_microservices.rabbitmq.connection import (
    RabbitMqChannels,
    RabbitMqConnectionManager,
    RabbitMqStatus,
)
from nestpy_microservices.rabbitmq.dependencies import require_aio_pika
from nestpy_microservices.rabbitmq.module import (
    RabbitMqModule,
    RabbitMqRoot,
    RabbitMqTransport,
)
from nestpy_microservices.rabbitmq.options import RabbitMqOptions
from nestpy_microservices.rabbitmq.publisher import RabbitMqPublisher
from nestpy_microservices.rabbitmq.server import RabbitMqServerTransport
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
    "RabbitMqClientTransport",
    "RabbitMqChannels",
    "RabbitMqConnectionManager",
    "ExchangeDeclaration",
    "QueueDeclaration",
    "RabbitMqModule",
    "RabbitMqOptions",
    "RabbitMqPublisher",
    "RabbitMqServerTransport",
    "RabbitMqRoot",
    "RabbitMqTopology",
    "RabbitMqTransport",
    "RabbitMqStatus",
    "compile_event_topology",
    "compile_reply_topology",
    "compile_rpc_topology",
    "merge_topologies",
    "require_aio_pika",
]
