"""Registry-backed message dispatch used by bus transports."""

import inspect
from collections.abc import Coroutine
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from tori_py_cqrs_core.context import BusHandles
from tori_py_cqrs_core.envelope import Envelope, ReplyEnvelope
from tori_py_cqrs_core.errors import (
    EnvelopeValidationError,
    InvalidHandlerRegistrationError,
)
from tori_py_cqrs_core.messages import Command, Event, Message, Query
from tori_py_cqrs_core.protocols import HandlerFunction, HandlerProvider
from tori_py_cqrs_core.registrations import HandlerKind, HandlerStyle, RegisteredHandler
from tori_py_cqrs_core.registry import HandlerRegistry


@dataclass(frozen=True, slots=True)
class EventInvocation:
    """One event handler coroutine and the registration that created it."""

    registration: RegisteredHandler
    operation: Coroutine[Any, Any, object]


@dataclass(slots=True)
class _CommandInvocation:
    bus: object
    active: bool = True


_command_invocations: ContextVar[tuple[_CommandInvocation, ...]] = ContextVar(
    "cqrs_command_invocations",
    default=(),
)


def is_command_bus_active(bus: object) -> bool:
    """Return whether this invocation is handling a command from ``bus``."""

    return any(
        invocation.active and invocation.bus is bus
        for invocation in _command_invocations.get()
    )


@contextmanager
def _command_invocation(bus: object):
    invocation = _CommandInvocation(bus)
    token = _command_invocations.set((*_command_invocations.get(), invocation))
    try:
        yield
    finally:
        # Child tasks copy context values, so invalidate the shared frame as well
        # as resetting this task's context.
        invocation.active = False
        _command_invocations.reset(token)


class Dispatcher:
    """Route envelopes to registered handlers and create request replies."""

    def __init__(
        self,
        registry: HandlerRegistry,
        provider: HandlerProvider[object],
        bus_handles: BusHandles,
    ) -> None:
        self._registry = registry
        self._provider = provider
        self._bus_handles = bus_handles

    async def dispatch_request(
        self,
        envelope: Envelope[Message],
        kind: HandlerKind,
        *,
        command_bus: object | None = None,
    ) -> ReplyEnvelope[object]:
        if envelope.correlation_id is None:
            raise EnvelopeValidationError("request envelope requires correlation_id")
        self._validate_request_category(envelope, kind)
        try:
            registration = self._registry.request_handler(kind, type(envelope.message))
            if kind is HandlerKind.COMMAND and command_bus is not None:
                with _command_invocation(command_bus):
                    result = await self._invoke(registration, envelope)
            else:
                result = await self._invoke(registration, envelope)
        except Exception as error:
            return ReplyEnvelope(
                reply_id=uuid4(),
                correlation_id=envelope.correlation_id,
                error=error,
            )
        return ReplyEnvelope(
            reply_id=uuid4(),
            correlation_id=envelope.correlation_id,
            result=result,
        )

    async def dispatch_event(self, envelope: Envelope[Message]) -> None:
        if not isinstance(envelope.message, Event):
            raise EnvelopeValidationError("event dispatcher requires an Event envelope")
        for registration in self._registry.event_handlers(type(envelope.message)):
            await self._invoke(registration, envelope)

    def event_invocations(
        self,
        envelope: Envelope[Message],
    ) -> tuple[EventInvocation, ...]:
        """Prepare matching event handler operations without awaiting them."""

        if not isinstance(envelope.message, Event):
            raise EnvelopeValidationError("event dispatcher requires an Event envelope")
        return tuple(
            EventInvocation(
                registration=registration,
                operation=self._invoke(registration, envelope),
            )
            for registration in self._registry.event_handlers(type(envelope.message))
        )

    @staticmethod
    def _validate_request_category(
        envelope: Envelope[Message],
        kind: HandlerKind,
    ) -> None:
        if kind is HandlerKind.COMMAND and not isinstance(envelope.message, Command):
            raise EnvelopeValidationError(
                "command dispatcher requires a Command envelope"
            )
        if kind is HandlerKind.QUERY and not isinstance(envelope.message, Query):
            raise EnvelopeValidationError("query dispatcher requires a Query envelope")
        if kind not in {HandlerKind.COMMAND, HandlerKind.QUERY}:
            raise EnvelopeValidationError(
                "request dispatcher requires Command or Query"
            )

    async def _invoke(
        self,
        registration: RegisteredHandler,
        envelope: Envelope[Message],
    ) -> object:
        context = self._bus_handles.context(envelope)
        async with self._provider.provide(registration, context) as handler:
            if registration.style is HandlerStyle.FUNCTION:
                function = cast(HandlerFunction[Message, object], handler)
                result = function(envelope.message, context)
            else:
                handle = getattr(handler, "handle", None)
                if not callable(handle):
                    raise InvalidHandlerRegistrationError(
                        "class handler must expose a callable handle method"
                    )
                result = handle(envelope.message)

            if not inspect.isawaitable(result):
                raise InvalidHandlerRegistrationError(
                    "handler must return an awaitable result"
                )
            return await result
