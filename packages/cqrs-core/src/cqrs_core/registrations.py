"""Handler metadata and explicit registration value objects."""

import inspect
from dataclasses import dataclass
from enum import StrEnum

from cqrs_core.errors import InvalidHandlerRegistrationError
from cqrs_core.messages import Command, Event, Message, Query


class HandlerKind(StrEnum):
    """The bus category handled by a registration."""

    COMMAND = "command"
    QUERY = "query"
    EVENT = "event"


class HandlerStyle(StrEnum):
    """The callable shape used by a handler."""

    CLASS = "class"
    FUNCTION = "function"


class TargetMode(StrEnum):
    """How a registered handler target is materialized."""

    INSTANCE = "instance"
    CLASS = "class"
    FUNCTION = "function"
    FACTORY = "factory"


@dataclass(frozen=True, slots=True)
class HandlerMetadata:
    """Metadata attached by a handler decorator."""

    kind: HandlerKind
    message_type: type[Message]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, HandlerKind):
            raise InvalidHandlerRegistrationError("handler kind must be a HandlerKind")
        _validate_message_kind(self.kind, self.message_type)


@dataclass(frozen=True, slots=True)
class RegisteredHandler:
    """A validated target waiting to be placed in the handler registry."""

    kind: HandlerKind
    message_type: type[Message]
    target: object
    style: HandlerStyle
    target_mode: TargetMode

    def __post_init__(self) -> None:
        if not isinstance(self.kind, HandlerKind):
            raise InvalidHandlerRegistrationError("handler kind must be a HandlerKind")
        if not isinstance(self.style, HandlerStyle):
            raise InvalidHandlerRegistrationError(
                "handler style must be a HandlerStyle"
            )
        if not isinstance(self.target_mode, TargetMode):
            raise InvalidHandlerRegistrationError(
                "handler target_mode must be a TargetMode"
            )
        _validate_message_kind(self.kind, self.message_type)
        if (
            self.target_mode is TargetMode.FUNCTION
            and self.style is not HandlerStyle.FUNCTION
        ):
            raise InvalidHandlerRegistrationError(
                "function target mode requires function handler style"
            )
        if (
            self.target_mode is not TargetMode.FUNCTION
            and self.style is not HandlerStyle.CLASS
        ):
            raise InvalidHandlerRegistrationError(
                "class target mode requires class handler style"
            )


HANDLER_METADATA_ATTRIBUTE = "__cqrs_handler_metadata__"


def _validate_message_kind(kind: HandlerKind, message_type: type[Message]) -> None:
    if not isinstance(message_type, type) or not issubclass(message_type, Message):
        raise InvalidHandlerRegistrationError(
            "handler message_type must be a Message subclass"
        )
    if message_type in {Message, Command, Query, Event}:
        raise InvalidHandlerRegistrationError(
            "handler message_type must be a concrete Message subclass"
        )

    expected_base: type[Message]
    if kind is HandlerKind.COMMAND:
        expected_base = Command
    elif kind is HandlerKind.QUERY:
        expected_base = Query
    else:
        expected_base = Event

    if not issubclass(message_type, expected_base):
        raise InvalidHandlerRegistrationError(
            f"{kind.value} handler message_type must inherit from "
            f"{expected_base.__name__}"
        )


def _decorate(
    kind: HandlerKind,
    message_type: type[Message],
    target: object,
    *,
    style: HandlerStyle,
) -> object:
    _validate_message_kind(kind, message_type)
    if style is HandlerStyle.CLASS and not inspect.isclass(target):
        raise InvalidHandlerRegistrationError(
            "class handler decorator requires a class"
        )
    if style is HandlerStyle.FUNCTION and not inspect.isfunction(target):
        raise InvalidHandlerRegistrationError(
            "function handler decorator requires a function"
        )
    if HANDLER_METADATA_ATTRIBUTE in target.__dict__:
        raise InvalidHandlerRegistrationError("handler already has CQRS metadata")

    setattr(target, HANDLER_METADATA_ATTRIBUTE, HandlerMetadata(kind, message_type))
    return target


def _decorator(
    kind: HandlerKind,
    message_type: type[Message],
    *,
    style: HandlerStyle,
):
    def decorate(target: object) -> object:
        return _decorate(kind, message_type, target, style=style)

    return decorate


def CommandHandler(message_type: type[Message]):
    """Decorate a class as a command handler."""

    return _decorator(HandlerKind.COMMAND, message_type, style=HandlerStyle.CLASS)


def QueryHandler(message_type: type[Message]):
    """Decorate a class as a query handler."""

    return _decorator(HandlerKind.QUERY, message_type, style=HandlerStyle.CLASS)


def EventsHandler(message_type: type[Message]):
    """Decorate a class as an event handler."""

    return _decorator(HandlerKind.EVENT, message_type, style=HandlerStyle.CLASS)


def handles(message_type: type[Message]):
    """Decorate a function handler for any supported message category."""

    if not isinstance(message_type, type) or not issubclass(message_type, Message):
        raise InvalidHandlerRegistrationError(
            "function handler message_type must be a Message subclass"
        )
    if issubclass(message_type, Command):
        kind = HandlerKind.COMMAND
    elif issubclass(message_type, Query):
        kind = HandlerKind.QUERY
    elif issubclass(message_type, Event):
        kind = HandlerKind.EVENT
    else:
        raise InvalidHandlerRegistrationError(
            "function handler message_type must be Command, Query, or Event"
        )
    return _decorator(kind, message_type, style=HandlerStyle.FUNCTION)


def get_handler_metadata(target: object) -> HandlerMetadata | None:
    """Read decorator metadata from a handler target or its class."""

    owner = target
    if not isinstance(target, type) and not inspect.isfunction(target):
        owner = type(target)
    metadata = owner.__dict__.get(HANDLER_METADATA_ATTRIBUTE)
    return metadata if isinstance(metadata, HandlerMetadata) else None


def target_mode_for(target: object) -> TargetMode:
    """Determine the explicit target mode for a decorated handler target."""

    if inspect.isfunction(target):
        return TargetMode.FUNCTION
    if isinstance(target, type):
        return TargetMode.CLASS
    return TargetMode.INSTANCE


def style_for(target: object) -> HandlerStyle:
    """Determine whether a target uses class or function handler invocation."""

    return (
        HandlerStyle.FUNCTION
        if target_mode_for(target) is TargetMode.FUNCTION
        else HandlerStyle.CLASS
    )
