"""Lazy public facade for the RabbitMQ native Streams adapter."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from persistent_streams_rabbitmq._capabilities import (
        RABBITMQ_START_MODE_CAPABILITIES,
    )
    from persistent_streams_rabbitmq._envelope import (
        CONTENT_TYPE,
        EnvelopeLimits,
        RecordEnvelope,
        decode_amqp_message,
        decode_envelope,
        encode_amqp_message,
        encode_envelope,
    )
    from persistent_streams_rabbitmq.errors import (
        EnvelopeError,
        RabbitMqPersistentStreamsError,
        TopologyConflictError,
    )
    from persistent_streams_rabbitmq.log import (
        RabbitMqPartitionLease,
        RabbitMqPersistentLog,
        TopologyPreflight,
    )
    from persistent_streams_rabbitmq.nestpy import (
        RabbitMqPersistentStreamsModule,
        RabbitMqStreamAdapterFactory,
    )
    from persistent_streams_rabbitmq.options import (
        DeclarationMode,
        RabbitMqConnectionOptions,
        RabbitMqPersistentStreamsOptions,
        RabbitMqTlsOptions,
        SaslMechanism,
    )

__all__ = [
    "CONTENT_TYPE",
    "DeclarationMode",
    "EnvelopeError",
    "EnvelopeLimits",
    "RABBITMQ_START_MODE_CAPABILITIES",
    "RabbitMqConnectionOptions",
    "RabbitMqPartitionLease",
    "RabbitMqPersistentLog",
    "RabbitMqPersistentStreamsError",
    "RabbitMqPersistentStreamsModule",
    "RabbitMqPersistentStreamsOptions",
    "RabbitMqStreamAdapterFactory",
    "RabbitMqTlsOptions",
    "RecordEnvelope",
    "SaslMechanism",
    "TopologyConflictError",
    "TopologyPreflight",
    "decode_amqp_message",
    "decode_envelope",
    "encode_amqp_message",
    "encode_envelope",
]

_MODULES = {
    "CONTENT_TYPE": "_envelope",
    "EnvelopeLimits": "_envelope",
    "RecordEnvelope": "_envelope",
    "decode_amqp_message": "_envelope",
    "decode_envelope": "_envelope",
    "encode_amqp_message": "_envelope",
    "encode_envelope": "_envelope",
    "RABBITMQ_START_MODE_CAPABILITIES": "_capabilities",
    "DeclarationMode": "options",
    "RabbitMqConnectionOptions": "options",
    "RabbitMqPersistentStreamsOptions": "options",
    "RabbitMqTlsOptions": "options",
    "SaslMechanism": "options",
    "EnvelopeError": "errors",
    "RabbitMqPersistentStreamsError": "errors",
    "TopologyConflictError": "errors",
    "RabbitMqPartitionLease": "log",
    "RabbitMqPersistentLog": "log",
    "TopologyPreflight": "log",
    "RabbitMqPersistentStreamsModule": "nestpy",
    "RabbitMqStreamAdapterFactory": "nestpy",
}


def __getattr__(name: str) -> Any:
    try:
        module = _MODULES[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value
