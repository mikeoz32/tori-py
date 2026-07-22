"""CQRS transport and event-error configuration."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from cqrs_core import EventErrorHandler, InMemoryTransport, Transport

from nestpy_cqrs.errors import CqrsConfigurationError

type TransportFactory = Callable[[], Transport | Awaitable[Transport]]


def _command_transport() -> Transport:
    return InMemoryTransport(name="nestpy-cqrs-command")


def _query_transport() -> Transport:
    return InMemoryTransport(name="nestpy-cqrs-query")


def _event_transport() -> Transport:
    return InMemoryTransport(name="nestpy-cqrs-event")


@dataclass(frozen=True, slots=True)
class CqrsModuleOptions:
    """Transport factories and event failure policy for one CQRS graph."""

    command_transport_factory: TransportFactory = _command_transport
    query_transport_factory: TransportFactory = _query_transport
    event_transport_factory: TransportFactory = _event_transport
    event_error_handler: EventErrorHandler | None = None

    def __post_init__(self) -> None:
        for name in (
            "command_transport_factory",
            "query_transport_factory",
            "event_transport_factory",
        ):
            if not callable(getattr(self, name)):
                raise CqrsConfigurationError(f"{name} must be callable")
        if self.event_error_handler is not None and not callable(
            self.event_error_handler
        ):
            raise CqrsConfigurationError("event_error_handler must be callable")


__all__ = ["CqrsModuleOptions", "TransportFactory"]
