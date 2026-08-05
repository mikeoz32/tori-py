"""Owned aio-pika connection, channels, and framework recovery coordination."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

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
    RECOVERING = "recovering"
    FAILED = "failed"
    CLOSED = "closed"


class RabbitMqChannelRole(StrEnum):
    CONSUMER = "consumer"
    PUBLISHER = "publisher"
    REPLY = "reply"


class RabbitMqRecoveryListener(Protocol):
    async def connection_lost(self, error: BaseException | None) -> None: ...

    async def connection_recovered(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RabbitMqChannels:
    consumer: object
    publisher: object
    reply: object


class RabbitMqConnectionManager:
    """Own one robust socket and framework-recovered channel resources."""

    def __init__(self, options: RabbitMqOptions) -> None:
        self.options = options
        self._status = RabbitMqStatus.CREATED
        self._status_events: asyncio.Queue[RabbitMqStatus] = asyncio.Queue()
        self._connection: Any | None = None
        self._channels: RabbitMqChannels | None = None
        self._listeners: list[RabbitMqRecoveryListener] = []
        self._lock = asyncio.Lock()
        self._recovery_lock = asyncio.Lock()
        self._fence_lock = asyncio.Lock()
        self._closing = False
        self._recovery_error: BaseException | None = None
        self._generation = 0
        self._recovery_finished = asyncio.Event()

    @property
    def status(self) -> RabbitMqStatus:
        return self._status

    @property
    def channels(self) -> RabbitMqChannels:
        channels = self._channels
        if channels is None or self._status not in {
            RabbitMqStatus.READY,
            RabbitMqStatus.RECOVERING,
        }:
            raise TransportStateError("RabbitMQ channels are not ready")
        return channels

    @property
    def recovery_error(self) -> BaseException | None:
        return self._recovery_error

    @property
    def generation(self) -> int:
        return self._generation

    async def on_module_init(self) -> None:
        await self.start()

    async def on_application_shutdown(self) -> None:
        await self.close()

    def register_recovery_listener(self, listener: RabbitMqRecoveryListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unregister_recovery_listener(self, listener: RabbitMqRecoveryListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def start(self) -> None:
        async with self._lock:
            if self._status is RabbitMqStatus.READY:
                return
            if self._status is RabbitMqStatus.CLOSED:
                raise TransportStateError("RabbitMQ manager is closed")
            self._set_status(RabbitMqStatus.CONNECTING)
            connection: Any | None = None
            opened_channels: list[Any] = []
            try:
                aio_pika = require_aio_pika()
                connection = await aio_pika.connect_robust(
                    self.options.url,
                    heartbeat=self.options.heartbeat,
                    timeout=self.options.connection_timeout,
                    reconnect_interval=self.options.reconnect_interval,
                    client_properties={"connection_name": self.options.connection_name},
                )
                consumer = await connection.channel(publisher_confirms=False)
                opened_channels.append(consumer)
                publisher = await connection.channel(
                    publisher_confirms=True,
                    on_return_raises=True,
                )
                opened_channels.append(publisher)
                reply = await connection.channel(publisher_confirms=False)
                opened_channels.append(reply)
                connection.close_callbacks.add(self._on_connection_lost)
                connection.reconnect_callbacks.add(self._on_connection_recovered)
            except BaseException as error:
                cleanup_errors = await _close_resources(opened_channels, connection)
                self._set_status(RabbitMqStatus.FAILED)
                if not isinstance(error, Exception):
                    _add_cleanup_notes(error, cleanup_errors)
                    raise
                failure = RabbitMqConnectionError(
                    "RabbitMQ connection or channel acquisition failed"
                )
                _add_cleanup_notes(failure, cleanup_errors)
                raise failure from error
            self._connection = connection
            self._channels = RabbitMqChannels(consumer, publisher, reply)
            self._recovery_error = None
            self._set_status(RabbitMqStatus.READY)

    async def declare(
        self,
        topology: RabbitMqTopology,
        *,
        role: RabbitMqChannelRole,
    ) -> dict[str, Any]:
        """Declare immutable topology on the explicitly selected channel role."""

        if not isinstance(role, RabbitMqChannelRole):
            raise TypeError("role must be a RabbitMqChannelRole")
        channel: Any = getattr(self.channels, role.value)
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
                    robust=False,
                )
            for declaration in topology.queues:
                queues[declaration.name] = await channel.declare_queue(
                    declaration.name,
                    durable=declaration.durable,
                    exclusive=declaration.exclusive,
                    auto_delete=declaration.auto_delete,
                    arguments=dict(declaration.arguments),
                    robust=False,
                )
            for binding in topology.bindings:
                exchange = exchanges.get(binding.exchange)
                queue = queues.get(binding.queue)
                if exchange is None or queue is None:
                    raise RabbitMqTopologyError(
                        "topology binding references an undeclared resource"
                    )
                await queue.bind(
                    exchange,
                    routing_key=binding.routing_key,
                    arguments=dict(binding.arguments),
                    robust=False,
                )
            return queues
        except RabbitMqTopologyError:
            raise
        except Exception as error:
            raise RabbitMqTopologyError(
                f"RabbitMQ {role.value} topology declaration failed"
            ) from error

    async def close(self) -> None:
        async with self._lock:
            if self._status is RabbitMqStatus.CLOSED:
                return
            self._closing = True
            channels = self._channels
            connection = self._connection
            self._channels = None
            self._connection = None
            opened = (
                [channels.consumer, channels.publisher, channels.reply]
                if channels is not None
                else []
            )
            cleanup_errors = await _close_resources(opened, connection)
            self._set_status(RabbitMqStatus.CLOSED)
            if cleanup_errors:
                if isinstance(cleanup_errors[0], asyncio.CancelledError):
                    _add_cleanup_notes(cleanup_errors[0], cleanup_errors[1:])
                    raise cleanup_errors[0]
                failure = RabbitMqConnectionError("RabbitMQ resource cleanup failed")
                _add_cleanup_notes(failure, cleanup_errors)
                raise failure from cleanup_errors[0]

    async def notify_connection_lost(self, error: BaseException | None = None) -> None:
        """Fence registered transports after a deterministic connection-loss signal."""

        async with self._recovery_lock:
            if self._closing or self._status is RabbitMqStatus.CLOSED:
                return
            if self._status in {
                RabbitMqStatus.CREATED,
                RabbitMqStatus.CONNECTING,
                RabbitMqStatus.RECOVERING,
                RabbitMqStatus.FAILED,
            }:
                return
            self._generation += 1
            self._set_status(RabbitMqStatus.RECOVERING)
            failures = await _notify_listeners(
                tuple(self._listeners), "connection_lost", error
            )
            if failures:
                self._recovery_error = failures[0]
                self._set_status(RabbitMqStatus.FAILED)

    async def fence_connection(
        self,
        error: BaseException,
        *,
        generation: int | None = None,
    ) -> None:
        """Close the current socket so uncertain deliveries can redeliver."""

        observed_generation = self._generation if generation is None else generation
        async with self._fence_lock:
            if observed_generation != self._generation:
                return
            if self._closing or self._status is RabbitMqStatus.CLOSED:
                return
            if self._status is RabbitMqStatus.RECOVERING:
                await asyncio.wait_for(
                    self._recovery_finished.wait(),
                    timeout=self.options.connection_timeout,
                )
                if observed_generation != self._generation:
                    return
            if self._status is not RabbitMqStatus.READY:
                return
            await self.notify_connection_lost(error)
            connection = self._connection
            transport = getattr(connection, "transport", None)
            native_connection = getattr(transport, "connection", None)
            close = getattr(native_connection, "close", None)
            if not callable(close):
                self._recovery_error = error
                self._set_status(RabbitMqStatus.FAILED)
                raise RabbitMqConnectionError(
                    "RabbitMQ connection could not be fenced"
                ) from error
            try:
                await asyncio.wait_for(
                    close(error if isinstance(error, Exception) else None),
                    timeout=self.options.connection_timeout,
                )
            except BaseException as close_error:
                self._recovery_error = close_error
                self._set_status(RabbitMqStatus.FAILED)
                if not isinstance(close_error, Exception):
                    raise
                raise RabbitMqConnectionError(
                    "RabbitMQ connection fencing failed"
                ) from close_error

    async def notify_connection_recovered(self) -> None:
        """Rebuild framework topology before reporting the connection ready."""

        async with self._recovery_lock:
            if self._closing or self._status is RabbitMqStatus.CLOSED:
                return
            if self._status not in {
                RabbitMqStatus.RECOVERING,
                RabbitMqStatus.FAILED,
            }:
                return
            self._set_status(RabbitMqStatus.RECOVERING)
            failures = await _notify_listeners(
                tuple(self._listeners), "connection_recovered"
            )
            if failures:
                self._recovery_error = failures[0]
                await _notify_listeners(
                    tuple(self._listeners),
                    "connection_lost",
                    failures[0],
                )
                self._set_status(RabbitMqStatus.FAILED)
                return
            self._recovery_error = None
            self._set_status(RabbitMqStatus.READY)

    async def statuses(self) -> AsyncIterator[RabbitMqStatus]:
        while True:
            yield await self._status_events.get()

    def unwrap(self) -> object:
        if self._connection is None:
            raise TransportStateError("RabbitMQ connection is not ready")
        return self._connection

    async def _on_connection_lost(
        self, _connection: object, error: BaseException | None
    ) -> None:
        await self.notify_connection_lost(error)

    async def _on_connection_recovered(self, _connection: object) -> None:
        await self.notify_connection_recovered()

    def _set_status(self, status: RabbitMqStatus) -> None:
        if self._status is status:
            return
        self._status = status
        if status in {
            RabbitMqStatus.READY,
            RabbitMqStatus.FAILED,
            RabbitMqStatus.CLOSED,
        }:
            self._recovery_finished.set()
        elif status in {RabbitMqStatus.CONNECTING, RabbitMqStatus.RECOVERING}:
            self._recovery_finished.clear()
        self._status_events.put_nowait(status)


async def _close_resources(
    opened_channels: list[Any], connection: Any | None
) -> list[BaseException]:
    failures: list[BaseException] = []
    for channel in reversed(opened_channels):
        try:
            await channel.close()
        except BaseException as error:
            failures.append(error)
    if connection is not None:
        try:
            await connection.close()
        except BaseException as error:
            failures.append(error)
    return failures


async def _notify_listeners(
    listeners: tuple[RabbitMqRecoveryListener, ...],
    method_name: str,
    *args: object,
) -> list[BaseException]:
    failures: list[BaseException] = []
    for listener in listeners:
        try:
            await getattr(listener, method_name)(*args)
        except BaseException as error:
            failures.append(error)
    return failures


def _add_cleanup_notes(
    failure: BaseException, cleanup_errors: list[BaseException]
) -> None:
    for error in cleanup_errors:
        failure.add_note(f"cleanup failure: {type(error).__name__}: {error}")


__all__ = [
    "RabbitMqChannelRole",
    "RabbitMqChannels",
    "RabbitMqConnectionManager",
    "RabbitMqStatus",
]
