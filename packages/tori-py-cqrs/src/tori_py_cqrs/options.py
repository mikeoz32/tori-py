"""CQRS transport and event-error configuration."""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from tori_py_cqrs_core import EventErrorHandler, InMemoryTransport, Transport

from tori_py_cqrs.errors import CqrsConfigurationError
from tori_py_cqrs.invocation import (
    CqrsInterceptor,
    CqrsInterceptorBinding,
    CqrsInterceptorPhase,
)

type TransportFactory = Callable[[], Transport | Awaitable[Transport]]


def _command_transport() -> Transport:
    return InMemoryTransport(name="tori-py-cqrs-command")


def _query_transport() -> Transport:
    return InMemoryTransport(name="tori-py-cqrs-query")


def _event_transport() -> Transport:
    return InMemoryTransport(name="tori-py-cqrs-event")


@dataclass(frozen=True, slots=True)
class CqrsModuleOptions:
    """Transport factories and event failure policy for one CQRS graph."""

    command_transport_factory: TransportFactory = _command_transport
    query_transport_factory: TransportFactory = _query_transport
    event_transport_factory: TransportFactory = _event_transport
    event_error_handler: EventErrorHandler | None = None
    command_interceptors: tuple[CqrsInterceptorBinding | CqrsInterceptor, ...] = ()
    query_interceptors: tuple[CqrsInterceptorBinding | CqrsInterceptor, ...] = ()
    event_interceptors: tuple[CqrsInterceptorBinding | CqrsInterceptor, ...] = ()

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
        for name in (
            "command_interceptors",
            "query_interceptors",
            "event_interceptors",
        ):
            object.__setattr__(self, name, _graph_bindings(getattr(self, name), name))


def _graph_bindings(
    items: Iterable[CqrsInterceptorBinding | CqrsInterceptor],
    name: str,
) -> tuple[CqrsInterceptorBinding, ...]:
    try:
        values = tuple(items)
    except TypeError as error:
        raise CqrsConfigurationError(f"{name} must be iterable") from error
    bindings: list[CqrsInterceptorBinding] = []
    for item in values:
        binding = (
            item
            if isinstance(item, CqrsInterceptorBinding)
            else CqrsInterceptorBinding(item, CqrsInterceptorPhase.GRAPH)
        )
        if binding.phase is not CqrsInterceptorPhase.GRAPH:
            raise CqrsConfigurationError(f"{name} accepts only graph-phase bindings")
        bindings.append(binding)
    return tuple(bindings)


__all__ = ["CqrsModuleOptions", "TransportFactory"]
