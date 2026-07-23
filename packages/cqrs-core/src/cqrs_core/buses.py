"""Application-facing command, query, and event bus facades."""

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from cqrs_core.dispatch import Dispatcher, EventInvocation, is_command_bus_active
from cqrs_core.envelope import DeliveryMetadata, DeliveryReceipt, Envelope
from cqrs_core.errors import (
    EnvelopeValidationError,
    InvalidLifecycleTransitionError,
    InvalidReplyCorrelationError,
    NestedCommandDispatchError,
    TransportNotStartedError,
    TransportStoppedError,
)
from cqrs_core.identity import message_type_for
from cqrs_core.messages import Command, Event, Message, Query
from cqrs_core.protocols import Transport, TransportConsumer
from cqrs_core.registrations import HandlerKind, RegisteredHandler

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True, slots=True)
class EventHandlerFailure:
    """Metadata delivered to the event handler error hook."""

    error: BaseException
    envelope: Envelope[Message]
    handler: str
    handler_id: int

    @property
    def message_id(self) -> UUID:
        """Return the failed event message ID."""

        return self.envelope.message_id

    @property
    def event_type(self) -> str:
        """Return the failed event's routing type."""

        return self.envelope.message_type


type EventErrorHandler = Callable[
    [EventHandlerFailure],
    Awaitable[object] | object,
]

type _ShutdownHook = Callable[[float | None], Awaitable[None]]


class _BusLifecycle:
    """Guard bus facade operations independently of transport behavior."""

    def __init__(self, transport: Transport) -> None:
        self.transport = transport
        self._state = _BusState.NEW
        self._lock = asyncio.Lock()
        self._startup_complete = asyncio.Event()
        self._shutdown_complete = asyncio.Event()

    async def start(self, consumer: TransportConsumer) -> None:
        async with self._lock:
            if self._state is not _BusState.NEW:
                raise InvalidLifecycleTransitionError(
                    operation="start bus",
                    state=self._state,
                )
            self._state = _BusState.STARTING
        try:
            await self.transport.start(consumer)
        except BaseException:
            async with self._lock:
                if self._state is _BusState.STARTING:
                    self._state = _BusState.NEW
                self._startup_complete.set()
            raise
        async with self._lock:
            stopped_during_start = self._state is not _BusState.STARTING
            if not stopped_during_start:
                self._state = _BusState.RUNNING
            self._startup_complete.set()
        if stopped_during_start:
            await self.transport.shutdown(timeout=0)
            raise TransportStoppedError("bus stopped during startup")

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

    async def shutdown(
        self,
        *,
        timeout: float | None,
        after_transport: _ShutdownHook | None = None,
    ) -> None:
        async with self._lock:
            if self._state is _BusState.STOPPED:
                return
            if self._state is _BusState.NEW:
                wait_for_existing = False
                wait_for_start = False
                self._state = _BusState.STOPPING
            elif self._state is _BusState.STOPPING:
                wait_for_existing = True
                wait_for_start = False
            else:
                wait_for_existing = False
                wait_for_start = self._state is _BusState.STARTING
                self._state = _BusState.STOPPING

        deadline = (
            None if timeout is None else asyncio.get_running_loop().time() + timeout
        )

        if wait_for_existing:
            if timeout is None:
                await self._shutdown_complete.wait()
            else:
                try:
                    await asyncio.wait_for(self._shutdown_complete.wait(), timeout)
                except TimeoutError:
                    self._startup_complete.set()
                    await self.transport.shutdown(timeout=0)
                    if after_transport is not None:
                        await after_transport(0)
                    await self._shutdown_complete.wait()
            return
        startup_expired = False
        try:
            if wait_for_start:
                remaining = _remaining(deadline)
                if remaining is not None and remaining <= 0:
                    startup_expired = True
                elif remaining is None:
                    await self._startup_complete.wait()
                else:
                    await asyncio.wait_for(self._startup_complete.wait(), remaining)
            if not startup_expired:
                await self.transport.shutdown(timeout=_remaining(deadline))
                if after_transport is not None:
                    await after_transport(_remaining(deadline))
        except TimeoutError:
            if wait_for_start:
                startup_expired = True
            else:
                raise
        finally:
            # A failed or cancelled shutdown cannot safely resume dispatch.
            async with self._lock:
                self._state = _BusState.STOPPED
                self._shutdown_complete.set()


class CommandBus:
    """Execute commands through a request transport."""

    def __init__(self, transport: Transport, dispatcher: Dispatcher) -> None:
        self._lifecycle = _BusLifecycle(transport)
        self._dispatcher = dispatcher

    async def start(self) -> None:
        await self._lifecycle.start(self._consume)

    async def _consume(self, envelope: Envelope[Message]):
        return await self._dispatcher.dispatch_request(
            envelope,
            HandlerKind.COMMAND,
            command_bus=self,
        )

    async def execute[ResultT](
        self,
        command: Command[ResultT],
        *,
        timeout: float | None = None,
    ) -> ResultT:
        if not isinstance(command, Command):
            raise EnvelopeValidationError("CommandBus.execute requires a Command")
        if is_command_bus_active(self):
            raise NestedCommandDispatchError(
                "cannot execute a command through the active CommandBus"
            )
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

    _TASK_CANCELLATION_GRACE = 0.1

    def __init__(
        self,
        transport: Transport,
        dispatcher: Dispatcher,
        *,
        error_handler: EventErrorHandler | None = None,
    ) -> None:
        self._lifecycle = _BusLifecycle(transport)
        self._dispatcher = dispatcher
        self._error_handler = error_handler
        self._event_tasks: set[asyncio.Task[object]] = set()
        self._event_task_context: dict[
            asyncio.Task[object], tuple[Envelope[Message], str, int]
        ] = {}
        self._event_task_generation: dict[asyncio.Task[object], int] = {}
        self._event_generation = 0
        self._force_drain_event = asyncio.Event()

    async def start(self) -> None:
        await self._lifecycle.start(self._consume)

    async def _consume(self, envelope: Envelope[Message]) -> None:
        self._event_generation += 1
        generation = self._event_generation
        for invocation in self._dispatcher.event_invocations(envelope):
            self._track_event_invocation(envelope, invocation, generation)

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
        try:
            await self._lifecycle.shutdown(
                timeout=timeout,
                after_transport=self._drain_after_transport,
            )
        except BaseException:
            await self._cancel_event_tasks()
            raise

    async def drain(self, *, timeout: float | None = None) -> None:
        """Wait for tracked event handlers and observers to finish."""

        await self._drain_event_tasks(timeout)

    def _track_event_invocation(
        self,
        envelope: Envelope[Message],
        invocation: EventInvocation,
        generation: int,
    ) -> None:
        handler_name, handler_id = _handler_identity(invocation.registration)
        task = asyncio.create_task(
            invocation.operation,
            name=f"event-handler:{handler_name}",
        )
        self._event_tasks.add(task)
        self._event_task_context[task] = (envelope, handler_name, handler_id)
        self._event_task_generation[task] = generation
        task.add_done_callback(self._event_task_done)

    def _event_task_done(self, task: asyncio.Task[object]) -> None:
        self._event_tasks.discard(task)
        context = self._event_task_context.pop(task, None)
        generation = self._event_task_generation.pop(task, None)
        if task.cancelled() or context is None:
            return
        error = task.exception()
        if error is None:
            return
        envelope, handler_name, handler_id = context
        observer = asyncio.create_task(
            self._report_failure(
                EventHandlerFailure(
                    error=error,
                    envelope=envelope,
                    handler=handler_name,
                    handler_id=handler_id,
                )
            ),
            name=f"event-error:{handler_name}",
        )
        self._event_tasks.add(observer)
        if generation is not None:
            self._event_task_generation[observer] = generation
        observer.add_done_callback(self._observer_done)

    def _observer_done(self, task: asyncio.Task[object]) -> None:
        self._event_tasks.discard(task)
        self._event_task_generation.pop(task, None)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except BaseException:
            logger.exception("Event error observer could not be inspected")
            return
        if error is not None:
            logger.error(
                "Event error observer failed",
                exc_info=(type(error), error, error.__traceback__),
            )

    async def _report_failure(self, failure: EventHandlerFailure) -> None:
        logger.error(
            "Event handler failed: message_id=%s event_type=%s handler=%s "
            "handler_id=%s",
            failure.message_id,
            failure.event_type,
            failure.handler,
            failure.handler_id,
            exc_info=(
                type(failure.error),
                failure.error,
                failure.error.__traceback__,
            ),
        )
        if self._error_handler is None:
            return
        try:
            result = self._error_handler(failure)
            if inspect.isawaitable(result):
                await result
        except Exception as error:
            logger.error(
                "Event error handler failed",
                exc_info=(type(error), error, error.__traceback__),
            )
        except asyncio.CancelledError as error:
            current_task = asyncio.current_task()
            if current_task is not None and current_task.cancelling():
                raise
            logger.error(
                "Event error handler was cancelled",
                exc_info=(type(error), error, error.__traceback__),
            )

    async def _drain_after_transport(self, timeout: float | None) -> None:
        try:
            if timeout is not None and timeout <= 0:
                self._force_drain_event.set()
            await self._drain_event_tasks(timeout)
        except asyncio.CancelledError:
            await self._cancel_event_tasks()
            raise

    async def _drain_event_tasks(self, timeout: float | None) -> None:
        generations = {
            generation
            for task in self._event_tasks
            if (generation := self._event_task_generation.get(task)) is not None
        }
        deadline = (
            None if timeout is None else asyncio.get_running_loop().time() + timeout
        )
        force_task = asyncio.create_task(self._force_drain_event.wait())
        try:
            while True:
                tasks = self._tasks_for_generations(generations)
                if not tasks:
                    return
                remaining = _remaining(deadline)
                if remaining is not None and remaining <= 0:
                    await self._cancel_event_tasks(
                        tasks,
                        generations=generations,
                        timeout=remaining,
                    )
                    return
                done, _ = await asyncio.wait(
                    {*tasks, force_task},
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if force_task in done:
                    await self._cancel_event_tasks(
                        tasks,
                        generations=generations,
                        timeout=remaining,
                    )
                    return
                if not done:
                    await self._cancel_event_tasks(
                        tasks,
                        generations=generations,
                        timeout=_remaining(deadline),
                    )
                    return
                await asyncio.sleep(0)
        finally:
            if not force_task.done():
                force_task.cancel()
            await asyncio.gather(force_task, return_exceptions=True)

    def _tasks_for_generations(
        self, generations: set[int]
    ) -> tuple[asyncio.Task[object], ...]:
        return tuple(
            task
            for task in self._event_tasks
            if self._event_task_generation.get(task) in generations
        )

    async def _cancel_event_tasks(
        self,
        tasks: tuple[asyncio.Task[object], ...] | None = None,
        *,
        generations: set[int] | None = None,
        timeout: float | None = None,
    ) -> None:
        pending = set(tasks or self._event_tasks)
        wait_timeout = self._TASK_CANCELLATION_GRACE if timeout is None else timeout
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=wait_timeout)
            await asyncio.sleep(0)
        follow_up = (
            set(self._tasks_for_generations(generations))
            if generations is not None
            else set(self._event_tasks)
        ) - pending
        for task in follow_up:
            if not task.done():
                task.cancel()
        if follow_up:
            await asyncio.wait(
                follow_up,
                timeout=wait_timeout,
            )
            await asyncio.sleep(0)


def _remaining(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return max(0.0, deadline - asyncio.get_running_loop().time())


def _handler_identity(registration: RegisteredHandler) -> tuple[str, int]:
    target = registration.target
    owner = (
        target
        if inspect.isclass(target) or inspect.isfunction(target)
        else type(target)
    )
    module = getattr(owner, "__module__", type(owner).__module__)
    qualname = getattr(owner, "__qualname__", type(owner).__qualname__)
    return f"{module}.{qualname}", id(target)
