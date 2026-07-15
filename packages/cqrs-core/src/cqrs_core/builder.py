"""Explicit CQRS graph builder."""

from dataclasses import dataclass

from cqrs_core.buses import (
    CommandBus,
    EventBus,
    EventErrorHandler,
    QueryBus,
)
from cqrs_core.context import BusHandles
from cqrs_core.dispatch import Dispatcher
from cqrs_core.errors import CqrsValidationError, InvalidHandlerRegistrationError
from cqrs_core.messages import Command, Event, Message, Query
from cqrs_core.protocols import HandlerProvider, Transport
from cqrs_core.provider import DefaultHandlerProvider
from cqrs_core.registrations import (
    HandlerKind,
    HandlerStyle,
    RegisteredHandler,
    TargetMode,
    get_handler_metadata,
    style_for,
    target_mode_for,
)
from cqrs_core.registry import HandlerRegistry


@dataclass(frozen=True, slots=True)
class CqrsBuses:
    """The three bus facades produced by the builder."""

    command_bus: CommandBus
    query_bus: QueryBus
    event_bus: EventBus


class CqrsBuilder:
    """Compose an explicit CQRS graph without automatic discovery."""

    def __init__(self) -> None:
        self._registrations: list[RegisteredHandler] = []
        self._command_transport: Transport | None = None
        self._query_transport: Transport | None = None
        self._event_transport: Transport | None = None
        self._provider: HandlerProvider[object] = DefaultHandlerProvider()
        self._event_error_handler: EventErrorHandler | None = None

    def add_command_handler(
        self,
        handler_or_message_type: object,
        handler: object | None = None,
    ) -> CqrsBuilder:
        return self._add_handler(HandlerKind.COMMAND, handler_or_message_type, handler)

    def add_query_handler(
        self,
        handler_or_message_type: object,
        handler: object | None = None,
    ) -> CqrsBuilder:
        return self._add_handler(HandlerKind.QUERY, handler_or_message_type, handler)

    def add_event_handler(
        self,
        handler_or_message_type: object,
        handler: object | None = None,
    ) -> CqrsBuilder:
        return self._add_handler(HandlerKind.EVENT, handler_or_message_type, handler)

    def add_command_handler_factory(
        self,
        message_type: type[Message],
        factory: object,
    ) -> CqrsBuilder:
        return self._add_factory(HandlerKind.COMMAND, message_type, factory)

    def add_query_handler_factory(
        self,
        message_type: type[Message],
        factory: object,
    ) -> CqrsBuilder:
        return self._add_factory(HandlerKind.QUERY, message_type, factory)

    def add_event_handler_factory(
        self,
        message_type: type[Message],
        factory: object,
    ) -> CqrsBuilder:
        return self._add_factory(HandlerKind.EVENT, message_type, factory)

    def with_command_transport(self, transport: Transport) -> CqrsBuilder:
        self._command_transport = transport
        return self

    def with_query_transport(self, transport: Transport) -> CqrsBuilder:
        self._query_transport = transport
        return self

    def with_event_transport(self, transport: Transport) -> CqrsBuilder:
        self._event_transport = transport
        return self

    def with_handler_provider(
        self,
        provider: HandlerProvider[object],
    ) -> CqrsBuilder:
        self._provider = provider
        return self

    def with_event_error_handler(
        self,
        error_handler: EventErrorHandler,
    ) -> CqrsBuilder:
        self._event_error_handler = error_handler
        return self

    def build(self) -> CqrsBuses:
        if self._command_transport is None:
            raise CqrsValidationError("command transport is required")
        if self._query_transport is None:
            raise CqrsValidationError("query transport is required")
        if self._event_transport is None:
            raise CqrsValidationError("event transport is required")
        if (
            len(
                {
                    id(self._command_transport),
                    id(self._query_transport),
                    id(self._event_transport),
                }
            )
            != 3
        ):
            raise CqrsValidationError("each bus requires a distinct transport instance")

        registry = HandlerRegistry.build(self._registrations)
        bus_handles = BusHandles()
        dispatcher = Dispatcher(registry, self._provider, bus_handles)
        buses = CqrsBuses(
            command_bus=CommandBus(self._command_transport, dispatcher),
            query_bus=QueryBus(self._query_transport, dispatcher),
            event_bus=EventBus(
                self._event_transport,
                dispatcher,
                error_handler=self._event_error_handler,
            ),
        )
        bus_handles.command_bus = buses.command_bus
        bus_handles.query_bus = buses.query_bus
        bus_handles.event_bus = buses.event_bus
        return buses

    def _add_handler(
        self,
        kind: HandlerKind,
        handler_or_message_type: object,
        handler: object | None,
    ) -> CqrsBuilder:
        if handler is None:
            target = handler_or_message_type
            metadata = get_handler_metadata(target)
            if metadata is None:
                raise InvalidHandlerRegistrationError(
                    "handler decorator metadata is required when message_type "
                    "is omitted"
                )
            if metadata.kind is not kind:
                raise InvalidHandlerRegistrationError(
                    f"handler metadata is for {metadata.kind.value}, not {kind.value}"
                )
            message_type = metadata.message_type
        else:
            message_type = handler_or_message_type
            target = handler
        message_type = self._validate_message_type(kind, message_type)

        self._registrations.append(
            RegisteredHandler(
                kind=kind,
                message_type=message_type,
                target=target,
                style=style_for(target),
                target_mode=target_mode_for(target),
            )
        )
        return self

    def _add_factory(
        self,
        kind: HandlerKind,
        message_type: type[Message],
        factory: object,
    ) -> CqrsBuilder:
        message_type = self._validate_message_type(kind, message_type)
        if not callable(factory):
            raise InvalidHandlerRegistrationError("handler factory must be callable")
        self._registrations.append(
            RegisteredHandler(
                kind=kind,
                message_type=message_type,
                target=factory,
                style=HandlerStyle.CLASS,
                target_mode=TargetMode.FACTORY,
            )
        )
        return self

    @staticmethod
    def _validate_message_type(
        kind: HandlerKind,
        message_type: object,
    ) -> type[Message]:
        if not isinstance(message_type, type) or not issubclass(message_type, Message):
            raise InvalidHandlerRegistrationError(
                "handler message_type must be a Message subclass"
            )
        if kind is HandlerKind.COMMAND:
            matches_kind = issubclass(message_type, Command)
        elif kind is HandlerKind.QUERY:
            matches_kind = issubclass(message_type, Query)
        else:
            matches_kind = issubclass(message_type, Event)
        if not matches_kind:
            raise InvalidHandlerRegistrationError(
                f"{kind.value} handler message_type has the wrong message category"
            )
        return message_type
