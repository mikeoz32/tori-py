"""Nestpy-native injectable CQRS handler decorators."""

from collections.abc import Callable
from typing import Any

from cqrs_core import (
    Command,
    Event,
    Message,
    Query,
)
from cqrs_core import (
    CommandHandler as CoreCommandHandler,
)
from cqrs_core import (
    EventsHandler as CoreEventsHandler,
)
from cqrs_core import (
    QueryHandler as CoreQueryHandler,
)
from nestpy import (
    BootstrapError,
    Scope,
    get_injectable_metadata,
    injectable,
)


def command_handler[InstanceT](
    message_type: type[Command[Any]],
    *,
    scope: Scope | str = Scope.SINGLETON,
    manage: bool = True,
) -> Callable[[type[InstanceT]], type[InstanceT]]:
    """Mark an injectable class as the handler for one command type."""

    return _handler_decorator(
        CoreCommandHandler,
        message_type,
        scope=scope,
        manage=manage,
    )


def query_handler[InstanceT](
    message_type: type[Query[Any]],
    *,
    scope: Scope | str = Scope.SINGLETON,
    manage: bool = True,
) -> Callable[[type[InstanceT]], type[InstanceT]]:
    """Mark an injectable class as the handler for one query type."""

    return _handler_decorator(
        CoreQueryHandler,
        message_type,
        scope=scope,
        manage=manage,
    )


def event_handler[InstanceT](
    message_type: type[Event],
    *,
    scope: Scope | str = Scope.SINGLETON,
    manage: bool = True,
) -> Callable[[type[InstanceT]], type[InstanceT]]:
    """Mark an injectable class as a handler for one event type."""

    return _handler_decorator(
        CoreEventsHandler,
        message_type,
        scope=scope,
        manage=manage,
    )


def _handler_decorator[InstanceT](
    core_decorator: Callable[
        [type[Message]],
        Callable[[type[InstanceT]], type[InstanceT]],
    ],
    message_type: type[Message],
    *,
    scope: Scope | str,
    manage: bool,
) -> Callable[[type[InstanceT]], type[InstanceT]]:
    decorate_handler = core_decorator(message_type)
    decorate_provider = injectable(scope=scope, manage=manage)

    def decorate(target: type[InstanceT]) -> type[InstanceT]:
        if get_injectable_metadata(target) is not None:
            raise BootstrapError(
                "injectable metadata is already declared on this target",
                code="reflection.duplicate_metadata",
            )
        return decorate_provider(decorate_handler(target))

    return decorate


__all__ = ["command_handler", "event_handler", "query_handler"]
