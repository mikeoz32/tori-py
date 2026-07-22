"""Explicit CQRS message-to-Nestpy-provider bindings."""

from dataclasses import dataclass

from cqrs_core import Command, Event, HandlerKind, Message, Query
from nestpy import BootstrapError, Token, validate_token

from nestpy_cqrs.errors import CqrsConfigurationError


@dataclass(frozen=True, slots=True)
class CqrsHandlerBinding:
    """Bind one CQRS message category to one visible Nestpy provider token."""

    kind: HandlerKind
    message_type: type[Message]
    token: Token

    def __post_init__(self) -> None:
        if not isinstance(self.kind, HandlerKind):
            raise CqrsConfigurationError("handler kind must be a HandlerKind")
        try:
            token = validate_token(self.token)
        except BootstrapError as error:
            raise CqrsConfigurationError(
                "handler token must be a class or string"
            ) from error
        object.__setattr__(self, "token", token)
        expected: type[Message]
        if self.kind is HandlerKind.COMMAND:
            expected = Command
        elif self.kind is HandlerKind.QUERY:
            expected = Query
        else:
            expected = Event
        if (
            not isinstance(self.message_type, type)
            or self.message_type in {Message, Command, Query, Event}
            or not issubclass(self.message_type, expected)
        ):
            raise CqrsConfigurationError(
                f"{self.kind.value} binding requires a concrete {expected.__name__}"
            )


def command_handler(
    message_type: type[Message],
    token: Token,
) -> CqrsHandlerBinding:
    """Bind one command type to a Nestpy provider token."""

    return CqrsHandlerBinding(HandlerKind.COMMAND, message_type, token)


def query_handler(
    message_type: type[Message],
    token: Token,
) -> CqrsHandlerBinding:
    """Bind one query type to a Nestpy provider token."""

    return CqrsHandlerBinding(HandlerKind.QUERY, message_type, token)


def event_handler(
    message_type: type[Message],
    token: Token,
) -> CqrsHandlerBinding:
    """Append one event-handler binding in declaration order."""

    return CqrsHandlerBinding(HandlerKind.EVENT, message_type, token)


__all__ = [
    "CqrsHandlerBinding",
    "command_handler",
    "event_handler",
    "query_handler",
]
