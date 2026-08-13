"""Dispatch context passed to function handlers and providers."""

from dataclasses import dataclass

from tori_py_cqrs_core.envelope import Envelope
from tori_py_cqrs_core.errors import InvalidLifecycleTransitionError
from tori_py_cqrs_core.messages import Message
from tori_py_cqrs_core.protocols import (
    CommandBusHandle,
    EventBusHandle,
    QueryBusHandle,
)


@dataclass(frozen=True, slots=True)
class HandlerContext:
    """Message metadata and bus handles available to function handlers."""

    envelope: Envelope[Message]
    command_bus: CommandBusHandle
    query_bus: QueryBusHandle
    event_bus: EventBusHandle


@dataclass(slots=True)
class BusHandles:
    """Late-bound bus handles used while the builder assembles the graph."""

    command_bus: CommandBusHandle | None = None
    query_bus: QueryBusHandle | None = None
    event_bus: EventBusHandle | None = None

    def context(self, envelope: Envelope[Message]) -> HandlerContext:
        if self.command_bus is None or self.query_bus is None or self.event_bus is None:
            raise InvalidLifecycleTransitionError(
                operation="create handler context",
                state="unbound bus handles",
            )
        return HandlerContext(
            envelope=envelope,
            command_bus=self.command_bus,
            query_bus=self.query_bus,
            event_bus=self.event_bus,
        )
