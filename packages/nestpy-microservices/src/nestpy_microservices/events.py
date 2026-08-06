"""Root-owned application event publication."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from nestpy import ShutdownContext

from nestpy_microservices.codec import MessageCodec, MsgspecJsonMessageCodec
from nestpy_microservices.errors import (
    TransportCapacityError,
    TransportStateError,
    TransportUnroutableError,
)
from nestpy_microservices.identities import EventIdentity, ServiceIdentity, utc_now
from nestpy_microservices.options import MicroservicesOptions
from nestpy_microservices.transport import (
    ClientTransport,
    ClientTransportFactory,
    Publication,
    PublicationReceipt,
    TransportStatus,
)
from nestpy_microservices.wire import EventEnvelope, freeze_headers


class _DispatcherState(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    QUIESCING = "quiescing"
    CLOSED = "closed"


class EventDispatcher:
    """Publish events from one immutable local service identity."""

    __slots__ = (
        "_close_lock",
        "_codec",
        "_identity",
        "_lifecycle_lock",
        "_options",
        "_state",
        "_tasks",
        "_transport",
    )

    def __init__(
        self,
        identity: ServiceIdentity,
        transport_factory: ClientTransportFactory,
        *,
        options: MicroservicesOptions | None = None,
        codec: MessageCodec | None = None,
    ) -> None:
        if not isinstance(identity, ServiceIdentity):
            raise TypeError("identity must be a ServiceIdentity")
        if not isinstance(transport_factory, ClientTransportFactory):
            raise TypeError("transport_factory must implement ClientTransportFactory")
        selected_options = options or MicroservicesOptions()
        if not isinstance(selected_options, MicroservicesOptions):
            raise TypeError("options must be MicroservicesOptions")
        transport = transport_factory.create()
        if not isinstance(transport, ClientTransport):
            raise TransportStateError(
                "client transport factory did not create a ClientTransport"
            )
        self._identity = identity
        self._options = selected_options
        self._codec = codec or MsgspecJsonMessageCodec(selected_options.message_limits)
        self._transport = transport
        self._state = _DispatcherState.CREATED
        self._tasks: set[asyncio.Task[object]] = set()
        self._lifecycle_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()

    @property
    def accepting(self) -> bool:
        """Whether new publications can currently be accepted."""

        return self._state is _DispatcherState.RUNNING

    @property
    def identity(self) -> ServiceIdentity:
        return self._identity

    @property
    def options(self) -> MicroservicesOptions:
        return self._options

    @property
    def codec(self) -> MessageCodec:
        return self._codec

    async def publish(
        self,
        event: str,
        schema_version: int,
        payload: object,
        *,
        headers: Mapping[str, object] | None = None,
        correlation_id: UUID | None = None,
        causation_id: UUID | None = None,
        occurred_at: datetime | None = None,
        require_route: bool = False,
    ) -> PublicationReceipt:
        """Encode and publish one event without exposing source routing controls."""

        task = asyncio.current_task()
        if task is None:
            raise TransportStateError("event publication requires an asyncio task")
        async with self._lifecycle_lock:
            if self._state is not _DispatcherState.RUNNING:
                raise TransportStateError(
                    "event dispatcher is not accepting publications"
                )
            if self._transport.status is not TransportStatus.RUNNING:
                raise TransportStateError("event dispatcher transport is not ready")
            if len(self._tasks) >= self._options.max_inflight_deliveries:
                raise TransportCapacityError("event publication task set is full")
            self._tasks.add(task)
        try:
            if not isinstance(require_route, bool):
                raise TypeError("require_route must be boolean")
            identity = EventIdentity(self.identity, event, schema_version)
            envelope = EventEnvelope(
                message_id=uuid4(),
                source=self.identity,
                event=identity.event,
                schema_version=identity.schema_version,
                occurred_at=utc_now() if occurred_at is None else occurred_at,
                correlation_id=correlation_id,
                causation_id=causation_id,
                headers=freeze_headers(headers, self.options.message_limits),
                payload=payload,
                limits=self.options.message_limits,
            )
            body = self.codec.encode_event(envelope)
            publication = Publication(
                message_id=envelope.message_id,
                routing_key=identity.routing_key,
                body=body,
                headers={},
                mandatory=True,
                correlation_id=envelope.correlation_id,
            )
            try:
                return await self._transport.publish_event(identity, publication)
            except TransportUnroutableError:
                if require_route:
                    raise
                return PublicationReceipt(envelope.message_id, utc_now(), routed=False)
        finally:
            self._tasks.discard(task)

    async def on_application_bootstrap(self) -> None:
        async with self._lifecycle_lock:
            if self._state is _DispatcherState.RUNNING:
                return
            if self._state is not _DispatcherState.CREATED:
                raise TransportStateError("event dispatcher cannot be restarted")
            self._state = _DispatcherState.STARTING
            try:
                await self._transport.start(receive_replies=False)
                if self._transport.status is not TransportStatus.RUNNING:
                    raise TransportStateError(
                        "event dispatcher transport did not become ready"
                    )
            except BaseException:
                self._state = _DispatcherState.CLOSED
                try:
                    await self._transport.close()
                except BaseException:
                    pass
                raise
            self._state = _DispatcherState.RUNNING

    async def on_application_quiesce(self, context: ShutdownContext) -> None:
        async with self._lifecycle_lock:
            if self._state is _DispatcherState.CLOSED:
                return
            if self._state is _DispatcherState.CREATED:
                self._state = _DispatcherState.QUIESCING
                return
            self._state = _DispatcherState.QUIESCING
        await self._drain_tasks(context.remaining)

    async def close(self) -> None:
        await self._close(drain=True)

    async def on_application_shutdown(self) -> None:
        await self._close(drain=False)

    async def _close(self, *, drain: bool) -> None:
        async with self._close_lock:
            async with self._lifecycle_lock:
                if self._state is _DispatcherState.CLOSED:
                    return
                self._state = _DispatcherState.QUIESCING
            if drain:
                await self._drain_tasks(lambda: None)
            try:
                await self._transport.close()
            finally:
                async with self._lifecycle_lock:
                    self._state = _DispatcherState.CLOSED

    async def _drain_tasks(self, remaining: Callable[[], float | None]) -> None:
        while self._tasks:
            tasks = tuple(self._tasks)
            timeout = remaining()
            if timeout is not None and timeout <= 0:
                await _cancel_tasks(tasks, remaining)
                return
            done, pending = await asyncio.wait(tasks, timeout=timeout)
            del done
            if pending:
                await _cancel_tasks(tuple(pending), remaining)
                return


async def _cancel_tasks(
    tasks: tuple[asyncio.Task[object], ...], remaining: Callable[[], float | None]
) -> None:
    for task in tasks:
        task.cancel()
        task.add_done_callback(_consume_task_exception)
    timeout = remaining()
    if tasks and (timeout is None or timeout > 0):
        await asyncio.wait(tasks, timeout=timeout)


def _consume_task_exception(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


__all__ = ["EventDispatcher"]
