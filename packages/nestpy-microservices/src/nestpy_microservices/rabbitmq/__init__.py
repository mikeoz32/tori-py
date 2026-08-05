"""Lazy RabbitMQ integration facade."""

from nestpy_microservices.errors import (
    RabbitMqConnectionError,
    RabbitMqError,
    RabbitMqTopologyError,
)
from nestpy_microservices.rabbitmq.client import RabbitMqClientTransport
from nestpy_microservices.rabbitmq.connection import (
    RabbitMqChannelRole,
    RabbitMqChannels,
    RabbitMqConnectionManager,
    RabbitMqStatus,
)
from nestpy_microservices.rabbitmq.dependencies import require_aio_pika
from nestpy_microservices.rabbitmq.module import (
    RabbitMqClientTransportFactory,
    RabbitMqModule,
    RabbitMqRoot,
    RabbitMqServerTransportFactory,
    RabbitMqTransport,
    rabbitmq_client_factory_token,
    rabbitmq_manager_token,
    rabbitmq_root_token,
    rabbitmq_server_factory_token,
)
from nestpy_microservices.rabbitmq.options import RabbitMqOptions
from nestpy_microservices.rabbitmq.publisher import RabbitMqPublisher
from nestpy_microservices.rabbitmq.server import (
    RabbitMqDeliveryMetadata,
    RabbitMqServerTransport,
)
from nestpy_microservices.rabbitmq.topology import (
    BindingDeclaration,
    ExchangeDeclaration,
    QueueDeclaration,
    RabbitMqTopology,
    compile_event_topology,
    compile_reply_topology,
    compile_rpc_topology,
    event_exchange_topology,
    merge_topologies,
)

__all__ = [
    "BindingDeclaration",
    "RabbitMqChannelRole",
    "RabbitMqClientTransport",
    "RabbitMqClientTransportFactory",
    "RabbitMqChannels",
    "RabbitMqConnectionManager",
    "ExchangeDeclaration",
    "QueueDeclaration",
    "RabbitMqConnectionError",
    "RabbitMqDeliveryMetadata",
    "RabbitMqError",
    "RabbitMqModule",
    "RabbitMqOptions",
    "RabbitMqPublisher",
    "RabbitMqServerTransport",
    "RabbitMqServerTransportFactory",
    "RabbitMqRoot",
    "RabbitMqTopology",
    "RabbitMqTransport",
    "RabbitMqStatus",
    "RabbitMqTopologyError",
    "compile_event_topology",
    "compile_reply_topology",
    "compile_rpc_topology",
    "event_exchange_topology",
    "merge_topologies",
    "rabbitmq_client_factory_token",
    "rabbitmq_manager_token",
    "rabbitmq_root_token",
    "rabbitmq_server_factory_token",
    "require_aio_pika",
]
