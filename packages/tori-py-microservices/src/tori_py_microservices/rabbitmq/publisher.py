"""RabbitMQ publisher-confirm adapter with lazy concrete AMQP classification."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tori_py_microservices.errors import (
    OptionalDependencyError,
    RabbitMqConnectionError,
    TransportIndeterminateError,
    TransportRejectedError,
    TransportTimeoutError,
    TransportUnroutableError,
)
from tori_py_microservices.identities import utc_now
from tori_py_microservices.rabbitmq.connection import RabbitMqConnectionManager
from tori_py_microservices.transport import Publication, PublicationReceipt


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
        fence_on_cancel: Callable[[], bool] | None = None,
    ) -> PublicationReceipt:
        if not isinstance(persistent, bool):
            raise TypeError("persistent must be boolean")
        observed_generation = getattr(self.manager, "generation", 0)
        publish_generation: int | None = None
        publish_started = False
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
            if observed_generation != getattr(self.manager, "generation", 0):
                raise TransportTimeoutError(
                    "RabbitMQ publication was interrupted before broker write"
                )
            publish_generation = getattr(self.manager, "generation", 0)
            publish_started = True
            result = await exchange.publish(
                message,
                routing_key=publication.routing_key,
                mandatory=publication.mandatory,
            )
        except asyncio.CancelledError as error:
            if not publish_started:
                raise TransportTimeoutError(
                    "RabbitMQ publication was cancelled before broker write"
                ) from error
            uncertainty = TransportIndeterminateError(
                "RabbitMQ publication outcome is indeterminate after cancellation"
            )
            manager_status = getattr(self.manager, "status", None)
            connection_is_ready = (
                manager_status is None
                or getattr(manager_status, "value", manager_status) == "ready"
            )
            if connection_is_ready and (fence_on_cancel is None or fence_on_cancel()):
                await self._fence(uncertainty, publish_generation, note_target=error)
            else:
                error.add_note("RabbitMQ connection fencing suppressed after reply")
            error.add_note("RabbitMQ publisher confirm may still be pending")
            raise uncertainty from error
        except Exception as error:
            if isinstance(error, OptionalDependencyError):
                raise
            if isinstance(error, TransportTimeoutError):
                raise
            amqp = _load_amqp_types()
            if not publish_started:
                raise RabbitMqConnectionError(
                    "RabbitMQ publication failed before broker write"
                ) from error
            if publish_started and publish_generation != getattr(
                self.manager, "generation", 0
            ):
                uncertainty = TransportIndeterminateError(
                    "RabbitMQ publication crossed a connection generation"
                )
                await self._fence(uncertainty, publish_generation)
                raise uncertainty from error
            if isinstance(error, amqp.publish_error) and publication.mandatory:
                raise TransportUnroutableError(
                    f"RabbitMQ publication was unroutable: {publication.routing_key}"
                ) from error
            if isinstance(error, amqp.delivery_error):
                raise TransportRejectedError(
                    "RabbitMQ publisher confirm rejected the publication"
                ) from error
            if isinstance(error, (*amqp.uncertainty_errors, TimeoutError, OSError)):
                uncertainty = TransportIndeterminateError(
                    "RabbitMQ publication outcome is indeterminate"
                )
                await self._fence(uncertainty, publish_generation)
                raise uncertainty from error
            raise RabbitMqConnectionError(
                "RabbitMQ publication failed before broker acceptance"
            ) from error
        if isinstance(result, amqp.ack):
            if publish_generation != getattr(self.manager, "generation", 0):
                uncertainty = TransportIndeterminateError(
                    "RabbitMQ publication confirm crossed a connection generation"
                )
                await self._fence(uncertainty, publish_generation)
                raise uncertainty
            return PublicationReceipt(
                publication.message_id,
                utc_now(),
                routed=publication.mandatory,
            )
        if isinstance(result, (amqp.nack, amqp.reject)):
            raise TransportRejectedError(
                "RabbitMQ publisher confirm rejected the publication"
            )
        uncertainty = TransportIndeterminateError(
            "RabbitMQ publisher did not provide a definitive confirmation"
        )
        await self._fence(uncertainty, publish_generation)
        raise uncertainty

    async def _fence(
        self,
        uncertainty: BaseException,
        generation: int | None,
        *,
        note_target: BaseException | None = None,
    ) -> None:
        try:
            await self.manager.fence_connection(uncertainty, generation=generation)
        except BaseException as fence_error:
            (note_target or uncertainty).add_note(
                "RabbitMQ connection fencing failed: "
                f"{type(fence_error).__name__}: {fence_error}"
            )


def _load_aio_pika() -> Any:
    from tori_py_microservices.rabbitmq.dependencies import require_aio_pika

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
