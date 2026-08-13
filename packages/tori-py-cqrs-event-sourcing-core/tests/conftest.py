from collections.abc import Callable

import pytest
from tori_py_cqrs_event_sourcing_core import (
    EventSourcingLimits,
    EventStore,
    InMemoryEventStore,
)

type EventStoreFactory = Callable[[EventSourcingLimits | None], EventStore]


@pytest.fixture
def event_store_factory() -> EventStoreFactory:
    """Factory seam reused by EventStore semantic contract tests."""

    def create(limits: EventSourcingLimits | None = None) -> EventStore:
        return InMemoryEventStore(limits=limits)

    return create
