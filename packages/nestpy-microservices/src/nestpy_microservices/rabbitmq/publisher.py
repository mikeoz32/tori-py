"""RabbitMQ publisher-confirm adapter with no eager aio-pika import."""

from __future__ import annotations

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


class RabbitMqPublisher:
    """Publish persistent messages through the owned confirm channel."""

    def __init__(self, manager: RabbitMqConnectionManager) -> None:
        self.manager = manager

    async def publish(self, publication: Publication) -> PublicationReceipt:
        try:
            aio_pika = _load_aio_pika()
            message = aio_pika.Message(
                body=publication.body,
                headers=dict(publication.headers),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
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
                expiration=(
                    max(
                        0,
                        int(
                            (publication.expires_at - utc_now()).total_seconds() * 1000
                        ),
                    )
                    if publication.expires_at is not None
                    else None
                ),
            )
            publisher_channel: Any = self.manager.channels.publisher
            await publisher_channel.default_exchange.publish(
                message,
                routing_key=publication.routing_key,
                mandatory=publication.mandatory,
            )
        except Exception as error:
            if isinstance(error, OptionalDependencyError):
                raise
            if _is_unroutable(error):
                raise TransportUnroutableError(
                    f"RabbitMQ publication was unroutable: {publication.routing_key}"
                ) from error
            if _is_rejected(error):
                raise TransportRejectedError(
                    "RabbitMQ publication was rejected"
                ) from error
            if _is_connection_failure(error):
                raise TransportIndeterminateError(
                    "RabbitMQ publication outcome is indeterminate"
                ) from error
            if isinstance(error, (TransportUnroutableError, TransportRejectedError)):
                raise
            raise RabbitMqConnectionError("RabbitMQ publication failed") from error
        return PublicationReceipt(publication.message_id, utc_now(), True)


def _load_aio_pika() -> Any:
    from nestpy_microservices.rabbitmq.dependencies import require_aio_pika

    return require_aio_pika()


def _is_unroutable(error: BaseException) -> bool:
    return type(error).__name__ in {"DeliveryError", "UnroutableError"}


def _is_rejected(error: BaseException) -> bool:
    return type(error).__name__ in {"MessageNackError", "NackError"}


def _is_connection_failure(error: BaseException) -> bool:
    return type(error).__name__ in {
        "ChannelInvalidStateError",
        "ConnectionClosed",
        "ConnectionError",
        "AMQPConnectionError",
    }


__all__ = ["RabbitMqPublisher"]
