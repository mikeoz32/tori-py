"""Owned lazy aio-pika connection, channel, and topology declaration resources."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from nestpy_microservices.errors import (
    RabbitMqConnectionError,
    RabbitMqTopologyError,
    TransportStateError,
)
from nestpy_microservices.rabbitmq.dependencies import require_aio_pika
from nestpy_microservices.rabbitmq.options import RabbitMqOptions
from nestpy_microservices.rabbitmq.topology import RabbitMqTopology


class RabbitMqStatus(StrEnum):
    CREATED = "created"
    CONNECTING = "connecting"
    READY = "ready"
    FAILED = "failed"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class RabbitMqChannels:
    consumer: object
    publisher: object
    reply: object


class RabbitMqConnectionManager:
    """Own one robust connection and three independent channel concerns."""

    def __init__(self, options: RabbitMqOptions) -> None:
        self.options = options
        self._status = RabbitMqStatus.CREATED
        self._status_events: asyncio.Queue[RabbitMqStatus] = asyncio.Queue()
        self._connection: Any | None = None
        self._channels: RabbitMqChannels | None = None
        self._lock = asyncio.Lock()

    @property
    def status(self) -> RabbitMqStatus:
        return self._status

    @property
    def channels(self) -> RabbitMqChannels:
        channels = self._channels
        if channels is None:
            raise TransportStateError("RabbitMQ channels are not ready")
        return channels

    async def on_module_init(self) -> None:
        await self.start()

    async def on_application_shutdown(self) -> None:
        await self.close()

    async def start(self) -> None:
        async with self._lock:
            if self._status is RabbitMqStatus.READY:
                return
            if self._status is RabbitMqStatus.CLOSED:
                raise TransportStateError("RabbitMQ manager is closed")
            self._set_status(RabbitMqStatus.CONNECTING)
            try:
                aio_pika = require_aio_pika()
                connection = await aio_pika.connect_robust(
                    self.options.url,
                    heartbeat=self.options.heartbeat,
                    timeout=self.options.connection_timeout,
                    client_properties={"connection_name": self.options.connection_name},
                )
                consumer = await connection.channel(publisher_confirms=False)
                publisher = await connection.channel(publisher_confirms=True)
                reply = await connection.channel(publisher_confirms=False)
            except Exception as error:
                self._set_status(RabbitMqStatus.FAILED)
                raise RabbitMqConnectionError(
                    "RabbitMQ connection or channel acquisition failed"
                ) from error
            self._connection = connection
            self._channels = RabbitMqChannels(consumer, publisher, reply)
            self._set_status(RabbitMqStatus.READY)

    async def declare(self, topology: RabbitMqTopology) -> dict[str, Any]:
        """Declare one immutable topology on the consumer channel."""

        channel: Any = self.channels.consumer
        try:
            aio_pika = require_aio_pika()
            exchange_type = aio_pika.ExchangeType.TOPIC
            exchanges: dict[str, Any] = {}
            queues: dict[str, Any] = {}
            for declaration in topology.exchanges:
                exchanges[declaration.name] = await channel.declare_exchange(
                    declaration.name,
                    type=exchange_type,
                    durable=declaration.durable,
                    arguments=dict(declaration.arguments),
                )
            for declaration in topology.queues:
                queues[declaration.name] = await channel.declare_queue(
                    declaration.name,
                    durable=declaration.durable,
                    exclusive=declaration.exclusive,
                    auto_delete=declaration.auto_delete,
                    arguments=dict(declaration.arguments),
                )
            for binding in topology.bindings:
                exchange = exchanges.get(binding.exchange)
                queue = queues.get(binding.queue)
                if exchange is None or queue is None:
                    raise RabbitMqTopologyError(
                        "topology binding references an undeclared resource"
                    )
                await exchange.bind(
                    queue,
                    routing_key=binding.routing_key,
                    arguments=dict(binding.arguments),
                )
            return queues
        except RabbitMqTopologyError:
            raise
        except Exception as error:
            raise RabbitMqTopologyError(
                "RabbitMQ topology declaration failed"
            ) from error

    async def close(self) -> None:
        async with self._lock:
            if self._status is RabbitMqStatus.CLOSED:
                return
            channels = self._channels
            connection: Any = self._connection
            self._channels = None
            self._connection = None
            channels_to_close: tuple[Any, ...] = (
                (channels.reply, channels.publisher, channels.consumer)
                if channels is not None
                else ()
            )
            for channel in channels_to_close:
                try:
                    await channel.close()
                except Exception:
                    pass
            if connection is not None:
                try:
                    await connection.close()
                except Exception:
                    pass
            self._set_status(RabbitMqStatus.CLOSED)

    async def statuses(self):
        while True:
            yield await self._status_events.get()

    def unwrap(self) -> object:
        if self._connection is None:
            raise TransportStateError("RabbitMQ connection is not ready")
        return self._connection

    def _set_status(self, status: RabbitMqStatus) -> None:
        self._status = status
        self._status_events.put_nowait(status)


__all__ = [
    "RabbitMqChannels",
    "RabbitMqConnectionManager",
    "RabbitMqStatus",
]
