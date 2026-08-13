"""Owned aio-pika connection, channels, and framework recovery coordination."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from tori_py_microservices.errors import (
    RabbitMqConnectionError,
    RabbitMqTopologyError,
    TransportStateError,
)
from tori_py_microservices.rabbitmq.dependencies import require_aio_pika
from tori_py_microservices.rabbitmq.options import RabbitMqOptions
from tori_py_microservices.rabbitmq.topology import RabbitMqTopology


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
        self._status_events: asyncio.Queue[RabbitMqStatus] = asyncio.Queue(maxsize=8)
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
        self._listener_tasks: set[asyncio.Task[object]] = set()

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
                    self.options.connection_url,
                    heartbeat=self.options.heartbeat,
                    timeout=self.options.connection_timeout,
                    reconnect_interval=self.options.reconnect_interval,
                    ssl=self.options.tls,
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
                cleanup_errors = await _close_resources(
                    opened_channels,
                    connection,
                    timeout=self.options.connection_timeout,
                )
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
            async with self._recovery_lock:
                if self._status is RabbitMqStatus.CLOSED:
                    return
                self._closing = True
                listener_errors = await self._drain_listener_tasks()
                channels = self._channels
                connection = self._connection
                self._channels = None
                self._connection = None
            opened = (
                [channels.consumer, channels.publisher, channels.reply]
                if channels is not None
                else []
            )
            cleanup_errors = [
                *listener_errors,
                *await _close_resources(
                    opened,
                    connection,
                    timeout=self.options.connection_timeout,
                ),
            ]
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
            }:
                return
            self._generation += 1
            self._set_status(RabbitMqStatus.RECOVERING)
            failures = await self._notify_listeners(
                "connection_lost",
                error,
            )
            if failures:
                self._recovery_error = failures[0]
                self._set_status(RabbitMqStatus.RECOVERING)

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

        recovery_failure: BaseException | None = None
        async with self._recovery_lock:
            if self._closing or self._status is RabbitMqStatus.CLOSED:
                return
            if self._status not in {
                RabbitMqStatus.RECOVERING,
                RabbitMqStatus.FAILED,
            }:
                return
            self._set_status(RabbitMqStatus.RECOVERING)
            failures = await self._notify_listeners("connection_recovered")
            if failures:
                self._recovery_error = failures[0]
                await self._notify_listeners("connection_lost", failures[0])
                self._set_status(RabbitMqStatus.RECOVERING)
                recovery_failure = RabbitMqConnectionError(
                    "RabbitMQ recovery listener failed during reconnection"
                )
            else:
                self._recovery_error = None
                self._set_status(RabbitMqStatus.READY)
        if recovery_failure is not None:
            await self._force_native_connection_close(recovery_failure)

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

    async def _notify_listeners(
        self,
        method_name: str,
        *args: object,
    ) -> list[BaseException]:
        previous = await self._drain_listener_tasks()
        if previous:
            return previous
        return await _notify_listeners(
            tuple(self._listeners),
            method_name,
            *args,
            timeout=self.options.connection_timeout,
            task_registry=self._listener_tasks,
        )

    async def _drain_listener_tasks(self) -> list[BaseException]:
        tasks = tuple(self._listener_tasks)
        if not tasks:
            return []
        done, pending = await asyncio.wait(
            tasks,
            timeout=self.options.connection_timeout,
        )
        for task in pending:
            task.cancel()
        if pending:
            terminated, lingering = await asyncio.wait(
                pending,
                timeout=self.options.connection_timeout,
            )
        else:
            terminated, lingering = set(), set()
        results = await asyncio.gather(*(done | terminated), return_exceptions=True)
        failures = [
            result
            for result in results
            if isinstance(result, BaseException)
            and not isinstance(result, asyncio.CancelledError)
        ]
        if lingering:
            failures.append(
                TimeoutError("RabbitMQ recovery listener did not terminate")
            )
        return failures

    async def _force_native_connection_close(self, error: BaseException) -> None:
        connection = self._connection
        native = getattr(
            getattr(getattr(connection, "transport", None), "connection", None),
            "close",
            None,
        )
        if not callable(native):
            cleanup_errors = await _close_resources(
                [],
                connection,
                timeout=self.options.connection_timeout,
            )
            recovery_error = cleanup_errors[0] if cleanup_errors else error
        else:
            assert connection is not None
            try:
                await asyncio.wait_for(
                    native(error if isinstance(error, Exception) else None),
                    timeout=self.options.connection_timeout,
                )
            except BaseException as close_error:
                try:
                    await asyncio.wait_for(
                        connection.close(),
                        timeout=self.options.connection_timeout,
                    )
                except BaseException as fallback_error:
                    recovery_error = fallback_error
                else:
                    recovery_error = close_error
            else:
                recovery_error = error
        self._recovery_error = recovery_error
        self._set_status(RabbitMqStatus.FAILED)

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
        _put_coalescing_status(self._status_events, status, key=lambda value: value)


def _put_coalescing_status[T](
    queue: asyncio.Queue[T], value: T, *, key: Callable[[T], object]
) -> None:
    """Keep distinct pending states while collapsing repeated transitions."""

    pending: list[T] = []
    while not queue.empty():
        pending.append(queue.get_nowait())
    value_key = key(value)
    if pending and key(pending[-1]) == value_key:
        pending[-1] = value
    else:
        pending.append(value)
    if queue.maxsize:
        pending = pending[-queue.maxsize :]
    for item in pending:
        queue.put_nowait(item)


async def _close_resources(
    opened_channels: list[Any],
    connection: Any | None,
    *,
    timeout: float,
) -> list[BaseException]:
    channel_failures: list[BaseException] = []
    for channel in reversed(opened_channels):
        try:
            await asyncio.wait_for(channel.close(), timeout=timeout)
        except BaseException as error:
            channel_failures.append(error)
    if connection is not None:
        close_task = asyncio.create_task(connection.close())
        try:
            await asyncio.wait_for(asyncio.shield(close_task), timeout=timeout)
            return channel_failures
        except BaseException as error:
            native = getattr(
                getattr(getattr(connection, "transport", None), "connection", None),
                "close",
                None,
            )
            if callable(native):
                try:
                    await asyncio.wait_for(native(), timeout=timeout)
                    task_failures = await _cancel_resource_task(close_task, timeout)
                    return [*channel_failures, *task_failures]
                except BaseException as native_error:
                    task_failures = await _cancel_resource_task(close_task, timeout)
                    return [*channel_failures, error, native_error, *task_failures]
            task_failures = await _cancel_resource_task(close_task, timeout)
            return [*channel_failures, error, *task_failures]
    return channel_failures


async def _cancel_resource_task(
    task: asyncio.Task[object], timeout: float
) -> list[BaseException]:
    if task.done():
        if task.cancelled():
            return []
        error = task.exception()
        return [] if error is None else [error]
    task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except asyncio.CancelledError:
        if task.cancelled():
            return []
        raise
    except TimeoutError as error:
        task.add_done_callback(_consume_resource_task)
        return [error]
    except BaseException as error:
        return [error]
    return []


def _consume_resource_task(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


async def _notify_listeners(
    listeners: tuple[RabbitMqRecoveryListener, ...],
    method_name: str,
    *args: object,
    timeout: float,
    task_registry: set[asyncio.Task[object]],
) -> list[BaseException]:
    failures: list[BaseException] = []
    deadline = asyncio.get_running_loop().time() + timeout
    for listener in listeners:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            failures.append(TimeoutError("RabbitMQ recovery listener deadline expired"))
            continue
        task = asyncio.create_task(getattr(listener, method_name)(*args))
        task_registry.add(task)
        task.add_done_callback(
            lambda completed: _consume_task_exception(completed, task_registry)
        )
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=remaining)
        except TimeoutError as error:
            task.cancel()
            failures.append(error)
        except BaseException as error:
            failures.append(error)
    return failures


def _consume_task_exception(
    task: asyncio.Task[object], task_registry: set[asyncio.Task[object]]
) -> None:
    task_registry.discard(task)
    if not task.cancelled():
        task.exception()


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
