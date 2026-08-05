"""RabbitMQ publisher-confirm adapter with lazy concrete AMQP classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nestpy_microservices.errors import (
    OptionalDependencyError,
    RabbitMqConnectionError,
    TransportIndeterminateError,
    TransportRejectedError,
    TransportUnroutableError,
)
from nestpy_microservices.identities import utc_now
from nestpy_microservices.rabbitmq.connection import RabbitMqConnectionManager
from nestpy_microservices.transport import Publication, PublicationReceipt


@dataclass(frozen=True, slots=True)
class _AmqpTypes:
    publish_error: type[BaseException]
    delivery_error: type[BaseException]
    uncertainty_errors: tuple[type[BaseException], ...]
    ack: type[object]
    nack: type[object]
    reject: type[object]


class RabbitMqPublisher:
    """Publish messages through the owned confirm channel."""

    def __init__(self, manager: RabbitMqConnectionManager) -> None:
        self.manager = manager

    async def publish(
        self,
        publication: Publication,
        *,
        persistent: bool = True,
    ) -> PublicationReceipt:
        if not isinstance(persistent, bool):
            raise TypeError("persistent must be boolean")
        try:
            aio_pika = _load_aio_pika()
            amqp = _load_amqp_types()
            message = aio_pika.Message(
                body=publication.body,
                headers=dict(publication.headers),
                delivery_mode=(
                    aio_pika.DeliveryMode.PERSISTENT
                    if persistent
                    else aio_pika.DeliveryMode.NOT_PERSISTENT
                ),
                correlation_id=(
                    str(publication.correlation_id)
                    if publication.correlation_id is not None
                    else None
                ),
                reply_to=(
                    publication.reply_to.value
                    if publication.reply_to is not None
                    else None
                ),
                message_id=str(publication.message_id),
                expiration=publication.expires_at,
            )
            publisher_channel: Any = self.manager.channels.publisher
            exchange_name = self.manager.options.rpc_exchange
            if (
                isinstance(publication.native, tuple)
                and len(publication.native) == 2
                and isinstance(publication.native[0], str)
            ):
                exchange_name = publication.native[0]
            exchange = await publisher_channel.get_exchange(
                exchange_name,
                ensure=False,
            )
            result = await exchange.publish(
                message,
                routing_key=publication.routing_key,
                mandatory=publication.mandatory,
            )
        except Exception as error:
            if isinstance(error, OptionalDependencyError):
                raise
            amqp = _load_amqp_types()
            if isinstance(error, amqp.publish_error) and publication.mandatory:
                raise TransportUnroutableError(
                    f"RabbitMQ publication was unroutable: {publication.routing_key}"
                ) from error
            if isinstance(error, amqp.delivery_error):
                raise TransportRejectedError(
                    "RabbitMQ publisher confirm rejected the publication"
                ) from error
            if isinstance(error, (*amqp.uncertainty_errors, TimeoutError, OSError)):
                raise TransportIndeterminateError(
                    "RabbitMQ publication outcome is indeterminate"
                ) from error
            raise RabbitMqConnectionError(
                "RabbitMQ publication failed before broker acceptance"
            ) from error
        if isinstance(result, amqp.ack):
            return PublicationReceipt(
                publication.message_id,
                utc_now(),
                routed=publication.mandatory,
            )
        if isinstance(result, (amqp.nack, amqp.reject)):
            raise TransportRejectedError(
                "RabbitMQ publisher confirm rejected the publication"
            )
        raise TransportIndeterminateError(
            "RabbitMQ publisher did not provide a definitive confirmation"
        )


def _load_aio_pika() -> Any:
    from nestpy_microservices.rabbitmq.dependencies import require_aio_pika

    return require_aio_pika()


def _load_amqp_types() -> _AmqpTypes:
    from aio_pika import exceptions
    from aiormq import spec

    return _AmqpTypes(
        publish_error=exceptions.PublishError,
        delivery_error=exceptions.DeliveryError,
        uncertainty_errors=(
            exceptions.AMQPConnectionError,
            exceptions.ChannelInvalidStateError,
            exceptions.ConnectionClosed,
            exceptions.ChannelClosed,
        ),
        ack=spec.Basic.Ack,
        nack=spec.Basic.Nack,
        reject=spec.Basic.Reject,
    )


__all__ = ["RabbitMqPublisher"]
