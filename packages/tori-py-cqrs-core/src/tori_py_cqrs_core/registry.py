"""Immutable handler registry built during application composition."""

import inspect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from tori_py_cqrs_core.errors import (
    DuplicateCommandHandlerError,
    DuplicateQueryHandlerError,
    InvalidHandlerRegistrationError,
    MissingHandlerError,
)
from tori_py_cqrs_core.identity import message_type_for
from tori_py_cqrs_core.messages import Message
from tori_py_cqrs_core.registrations import HandlerKind, RegisteredHandler, TargetMode


@dataclass(frozen=True, slots=True)
class HandlerRegistry:
    """Read-only command, query, and event handler mappings."""

    commands: Mapping[type[Message], RegisteredHandler]
    queries: Mapping[type[Message], RegisteredHandler]
    events: Mapping[type[Message], tuple[RegisteredHandler, ...]]

    @classmethod
    def build(cls, registrations: Sequence[RegisteredHandler]) -> HandlerRegistry:
        commands: dict[type[Message], RegisteredHandler] = {}
        queries: dict[type[Message], RegisteredHandler] = {}
        events: dict[type[Message], list[RegisteredHandler]] = {}

        for registration in registrations:
            cls._validate_target(registration)

            if registration.kind is HandlerKind.COMMAND:
                if registration.message_type in commands:
                    raise DuplicateCommandHandlerError(
                        message_type=message_type_for(registration.message_type)
                    )
                commands[registration.message_type] = registration
            elif registration.kind is HandlerKind.QUERY:
                if registration.message_type in queries:
                    raise DuplicateQueryHandlerError(
                        message_type=message_type_for(registration.message_type)
                    )
                queries[registration.message_type] = registration
            elif registration.kind is HandlerKind.EVENT:
                registered_events = events.setdefault(registration.message_type, [])
                if any(
                    existing.target is registration.target
                    for existing in registered_events
                ):
                    raise InvalidHandlerRegistrationError(
                        "the same event handler cannot be registered twice"
                    )
                registered_events.append(registration)
            else:
                raise InvalidHandlerRegistrationError("handler kind is not supported")

        return cls(
            commands=MappingProxyType(commands),
            queries=MappingProxyType(queries),
            events=MappingProxyType(
                {
                    message_type: tuple(handlers)
                    for message_type, handlers in events.items()
                }
            ),
        )

    @staticmethod
    def _validate_target(registration: RegisteredHandler) -> None:
        target = registration.target
        if registration.target_mode is TargetMode.FUNCTION:
            if not callable(target) or not inspect.iscoroutinefunction(target):
                raise InvalidHandlerRegistrationError(
                    "function handler must be an async callable"
                )
            parameters = tuple(inspect.signature(target).parameters.values())
            if len(parameters) != 2 or any(
                parameter.kind
                not in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                }
                or parameter.default is not inspect.Parameter.empty
                for parameter in parameters
            ):
                raise InvalidHandlerRegistrationError(
                    "function handler must accept exactly (message, context)"
                )
            return

        if registration.target_mode is TargetMode.FACTORY:
            if not callable(target):
                raise InvalidHandlerRegistrationError(
                    "handler factory must be callable"
                )
            return

        if registration.target_mode is TargetMode.CLASS:
            if not inspect.isclass(target):
                raise InvalidHandlerRegistrationError(
                    "class handler target must be a class"
                )
            handle = getattr(target, "handle", None)
        else:
            handle = getattr(target, "handle", None)

        if not callable(handle) or not inspect.iscoroutinefunction(handle):
            raise InvalidHandlerRegistrationError(
                "class handler must expose an async handle method"
            )

    def request_handler(
        self,
        kind: HandlerKind,
        message_type: type[Message],
    ) -> RegisteredHandler:
        """Return the one command/query handler or raise a typed error."""

        if kind is HandlerKind.COMMAND:
            handlers = self.commands
        elif kind is HandlerKind.QUERY:
            handlers = self.queries
        else:
            raise InvalidHandlerRegistrationError(
                "request handler kind must be command or query"
            )
        handler = handlers.get(message_type)
        if handler is None:
            raise MissingHandlerError(message_type=message_type_for(message_type))
        return handler

    def event_handlers(
        self,
        message_type: type[Message],
    ) -> tuple[RegisteredHandler, ...]:
        """Return all event handlers in registration order."""

        return self.events.get(message_type, ())
