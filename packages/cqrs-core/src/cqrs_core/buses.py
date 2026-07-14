"""Application-facing command, query, and event bus facades."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import cast
from uuid import uuid4

from cqrs_core.dispatch import Dispatcher
from cqrs_core.envelope import DeliveryMetadata, DeliveryReceipt, Envelope
from cqrs_core.errors import (
    EnvelopeValidationError,
    InvalidLifecycleTransitionError,
    InvalidReplyCorrelationError,
    TransportNotStartedError,
    TransportStoppedError,
)
from cqrs_core.identity import message_type_for
from cqrs_core.messages import Command, Event, Message, Query
from cqrs_core.protocols import Transport, TransportConsumer
from cqrs_core.registrations import HandlerKind


def _envelope_for(message: Message, *, request: bool) -> Envelope[Message]:
    correlation_id = uuid4() if request else None
    now = datetime.now(UTC)
    return Envelope(
        message=message,
        message_type=message_type_for(type(message)),
        message_id=uuid4(),
        correlation_id=correlation_id,
        causation_id=None,
        headers={},
        delivery=DeliveryMetadata(delivery_id=uuid4(), enqueued_at=now),
    )


class _BusState(StrEnum):
    NEW = "new"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


class _BusLifecycle:
    """Guard bus facade operations independently of transport behavior."""

    def __init__(self, transport: Transport) -> None:
        self.transport = transport
        self._state = _BusState.NEW

    async def start(self, consumer: TransportConsumer) -> None:
        if self._state is not _BusState.NEW:
            raise InvalidLifecycleTransitionError(
                operation="start bus",
                state=self._state,
            )
        self._state = _BusState.STARTING
        try:
            await self.transport.start(consumer)
        except BaseException:
            self._state = _BusState.NEW
            raise
        self._state = _BusState.RUNNING

    def require_running(self) -> None:
        if self._state is _BusState.NEW:
            raise TransportNotStartedError("bus has not been started")
        if self._state is _BusState.STOPPED:
            raise TransportStoppedError("bus has been stopped")
        if self._state in {_BusState.STARTING, _BusState.STOPPING}:
            raise InvalidLifecycleTransitionError(
                operation="submit work",
                state=self._state,
            )

    async def shutdown(self, *, timeout: float | None) -> None:
        if self._state is _BusState.STOPPED:
            return
        if self._state is _BusState.STOPPING:
            return
        self._state = _BusState.STOPPING
        try:
            await self.transport.shutdown(timeout=timeout)
        finally:
            # A failed or cancelled shutdown cannot safely resume dispatch.
            self._state = _BusState.STOPPED


class CommandBus:
    """Execute commands through a request transport."""

    def __init__(self, transport: Transport, dispatcher: Dispatcher) -> None:
        self._lifecycle = _BusLifecycle(transport)
        self._dispatcher = dispatcher

    async def start(self) -> None:
        await self._lifecycle.start(self._consume)

    async def _consume(self, envelope: Envelope[Message]):
        return await self._dispatcher.dispatch_request(envelope, HandlerKind.COMMAND)

    async def execute[ResultT](
        self,
        command: Command[ResultT],
        *,
        timeout: float | None = None,
    ) -> ResultT:
        if not isinstance(command, Command):
            raise EnvelopeValidationError("CommandBus.execute requires a Command")
        self._lifecycle.require_running()
        envelope = _envelope_for(command, request=True)
        reply = await self._lifecycle.transport.request(envelope, timeout=timeout)
        assert envelope.correlation_id is not None
        if reply.correlation_id != envelope.correlation_id:
            raise InvalidReplyCorrelationError(
                expected=envelope.correlation_id,
                actual=reply.correlation_id,
            )
        if reply.error is not None:
            raise reply.error
        return cast(ResultT, reply.result)

    async def shutdown(self, *, timeout: float | None = None) -> None:
        await self._lifecycle.shutdown(timeout=timeout)


class QueryBus:
    """Execute queries through a request transport."""

    def __init__(self, transport: Transport, dispatcher: Dispatcher) -> None:
        self._lifecycle = _BusLifecycle(transport)
        self._dispatcher = dispatcher

    async def start(self) -> None:
        await self._lifecycle.start(self._consume)

    async def _consume(self, envelope: Envelope[Message]):
        return await self._dispatcher.dispatch_request(envelope, HandlerKind.QUERY)

    async def execute[ResultT](
        self,
        query: Query[ResultT],
        *,
        timeout: float | None = None,
    ) -> ResultT:
        if not isinstance(query, Query):
            raise EnvelopeValidationError("QueryBus.execute requires a Query")
        self._lifecycle.require_running()
        envelope = _envelope_for(query, request=True)
        reply = await self._lifecycle.transport.request(envelope, timeout=timeout)
        assert envelope.correlation_id is not None
        if reply.correlation_id != envelope.correlation_id:
            raise InvalidReplyCorrelationError(
                expected=envelope.correlation_id,
                actual=reply.correlation_id,
            )
        if reply.error is not None:
            raise reply.error
        return cast(ResultT, reply.result)

    async def shutdown(self, *, timeout: float | None = None) -> None:
        await self._lifecycle.shutdown(timeout=timeout)


class EventBus:
    """Publish events through a one-way transport."""

    def __init__(self, transport: Transport, dispatcher: Dispatcher) -> None:
        self._lifecycle = _BusLifecycle(transport)
        self._dispatcher = dispatcher

    async def start(self) -> None:
        await self._lifecycle.start(self._consume)

    async def _consume(self, envelope: Envelope[Message]) -> None:
        await self._dispatcher.dispatch_event(envelope)

    async def publish(
        self,
        event: Event,
        *,
        timeout: float | None = None,
    ) -> DeliveryReceipt:
        if not isinstance(event, Event):
            raise EnvelopeValidationError("EventBus.publish requires an Event")
        self._lifecycle.require_running()
        envelope = _envelope_for(event, request=False)
        return await self._lifecycle.transport.publish(envelope, timeout=timeout)

    async def shutdown(self, *, timeout: float | None = None) -> None:
        await self._lifecycle.shutdown(timeout=timeout)
