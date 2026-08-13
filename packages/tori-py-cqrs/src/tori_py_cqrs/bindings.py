"""Explicit CQRS message-to-ToriPy-provider bindings."""

from collections.abc import Iterable
from dataclasses import dataclass

from tori_py import BootstrapError, Token, validate_token
from tori_py_cqrs_core import Command, Event, HandlerKind, Message, Query

from tori_py_cqrs.errors import CqrsConfigurationError
from tori_py_cqrs.invocation import CqrsInterceptorBinding


@dataclass(frozen=True, slots=True)
class CqrsHandlerBinding:
    """Bind one CQRS message category to one visible ToriPy provider token."""

    kind: HandlerKind
    message_type: type[Message]
    token: Token
    interceptors: tuple[CqrsInterceptorBinding, ...] = ()

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
        try:
            interceptors = tuple(self.interceptors)
        except TypeError as error:
            raise CqrsConfigurationError("interceptors must be iterable") from error
        if any(not isinstance(item, CqrsInterceptorBinding) for item in interceptors):
            raise CqrsConfigurationError(
                "interceptors must contain CqrsInterceptorBinding values"
            )
        object.__setattr__(self, "interceptors", interceptors)
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


def bind_command_handler(
    message_type: type[Message],
    token: Token,
    *,
    interceptors: Iterable[CqrsInterceptorBinding] = (),
) -> CqrsHandlerBinding:
    """Bind one command type to a ToriPy provider token."""

    return CqrsHandlerBinding(
        HandlerKind.COMMAND,
        message_type,
        token,
        _binding_interceptors(interceptors),
    )


def bind_query_handler(
    message_type: type[Message],
    token: Token,
    *,
    interceptors: Iterable[CqrsInterceptorBinding] = (),
) -> CqrsHandlerBinding:
    """Bind one query type to a ToriPy provider token."""

    return CqrsHandlerBinding(
        HandlerKind.QUERY,
        message_type,
        token,
        _binding_interceptors(interceptors),
    )


def bind_event_handler(
    message_type: type[Message],
    token: Token,
    *,
    interceptors: Iterable[CqrsInterceptorBinding] = (),
) -> CqrsHandlerBinding:
    """Append one event-handler binding in declaration order."""

    return CqrsHandlerBinding(
        HandlerKind.EVENT,
        message_type,
        token,
        _binding_interceptors(interceptors),
    )


def _binding_interceptors(
    interceptors: Iterable[CqrsInterceptorBinding],
) -> tuple[CqrsInterceptorBinding, ...]:
    try:
        return tuple(interceptors)
    except TypeError as error:
        raise CqrsConfigurationError("interceptors must be iterable") from error


__all__ = [
    "CqrsHandlerBinding",
    "bind_command_handler",
    "bind_event_handler",
    "bind_query_handler",
]
