"""Registry-backed message dispatch used by bus transports."""

import inspect
from typing import cast
from uuid import uuid4

from cqrs_core.context import BusHandles
from cqrs_core.envelope import Envelope, ReplyEnvelope
from cqrs_core.errors import EnvelopeValidationError, InvalidHandlerRegistrationError
from cqrs_core.messages import Command, Event, Message, Query
from cqrs_core.protocols import HandlerFunction, HandlerProvider
from cqrs_core.registrations import HandlerKind, HandlerStyle, RegisteredHandler
from cqrs_core.registry import HandlerRegistry


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
    ) -> ReplyEnvelope[object]:
        if envelope.correlation_id is None:
            raise EnvelopeValidationError("request envelope requires correlation_id")
        self._validate_request_category(envelope, kind)
        try:
            registration = self._registry.request_handler(kind, type(envelope.message))
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
