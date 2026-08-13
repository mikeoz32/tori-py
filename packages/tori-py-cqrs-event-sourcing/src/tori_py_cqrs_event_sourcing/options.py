"""Immutable root configuration."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from tori_py import BootstrapError, Token, validate_token
from tori_py_cqrs_event_sourcing_core import (
    EventSchemaRegistry,
    EventSourcingUnitOfWork,
    EventStore,
)

from tori_py_cqrs_event_sourcing.errors import CqrsEventSourcingConfigurationError

type UnitOfWorkFactory = Callable[
    [EventStore], EventSourcingUnitOfWork | Awaitable[EventSourcingUnitOfWork]
]


def default_unit_of_work_factory(store: EventStore) -> EventSourcingUnitOfWork:
    """Create the standard framework-neutral Unit of Work."""

    return EventSourcingUnitOfWork(store)


@dataclass(frozen=True, slots=True)
class CqrsEventSourcingOptions:
    """Configuration captured by one keyed event-sourcing root."""

    store: Token
    schemas: EventSchemaRegistry
    unit_of_work_factory: UnitOfWorkFactory = default_unit_of_work_factory

    def __post_init__(self) -> None:
        try:
            store = validate_token(self.store)
        except BootstrapError as error:
            raise CqrsEventSourcingConfigurationError(
                "store must be a ToriPy provider token"
            ) from error
        if not isinstance(self.schemas, EventSchemaRegistry):
            raise CqrsEventSourcingConfigurationError(
                "schemas must be an EventSchemaRegistry"
            )
        if not callable(self.unit_of_work_factory):
            raise CqrsEventSourcingConfigurationError(
                "unit_of_work_factory must be callable"
            )
        object.__setattr__(self, "store", store)


__all__ = [
    "CqrsEventSourcingOptions",
    "UnitOfWorkFactory",
    "default_unit_of_work_factory",
]
