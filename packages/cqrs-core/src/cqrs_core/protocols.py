"""Framework-agnostic protocols for handlers, providers, and transports."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from cqrs_core.envelope import DeliveryReceipt, Envelope, ReplyEnvelope
from cqrs_core.messages import Command, Event, Message, Query


@runtime_checkable
class AsyncMessageHandler[MessageT: Message, ResultT](Protocol):
    """Protocol implemented by class-based async handlers."""

    async def handle(self, message: MessageT) -> ResultT:
        """Handle one typed message."""


@runtime_checkable
class HandlerRegistration(Protocol):
    """Minimal metadata required by a handler provider."""

    @property
    def message_type(self) -> type[Message]:
        """Return the message class handled by the registration."""


@runtime_checkable
class DispatchContext(Protocol):
    """Context visible to provider implementations during one dispatch."""

    @property
    def envelope(self) -> Envelope[Message]:
        """Return the envelope currently being dispatched."""


@runtime_checkable
class HandlerProvider[HandlerT](Protocol):
    """Create a handler scope and clean it up after dispatch."""

    def provide(
        self,
        registration: HandlerRegistration,
        context: DispatchContext,
    ) -> AbstractAsyncContextManager[HandlerT]:
        """Return an async context manager for one handler invocation."""


@runtime_checkable
class CommandBusHandle(Protocol):
    """Minimal command bus handle exposed through handler context."""

    async def execute(
        self,
        command: Command[object],
        *,
        timeout: float | None = None,
    ) -> object:
        """Execute a command from a function handler."""


@runtime_checkable
class QueryBusHandle(Protocol):
    """Minimal query bus handle exposed through handler context."""

    async def execute(
        self,
        query: Query[object],
        *,
        timeout: float | None = None,
    ) -> object:
        """Execute a query from a function handler."""


@runtime_checkable
class EventBusHandle(Protocol):
    """Minimal event bus handle exposed through handler context."""

    async def publish(
        self,
        event: Event,
        *,
        timeout: float | None = None,
    ) -> DeliveryReceipt:
        """Publish an event from a function handler."""


class FunctionHandlerContext(Protocol):
    """Metadata and bus handles passed to a function handler."""

    @property
    def envelope(self) -> Envelope[Message]:
        """Return the envelope currently being handled."""

    @property
    def command_bus(self) -> CommandBusHandle:
        """Return the command bus available to the handler."""

    @property
    def query_bus(self) -> QueryBusHandle:
        """Return the query bus available to the handler."""

    @property
    def event_bus(self) -> EventBusHandle:
        """Return the event bus available to the handler."""


@runtime_checkable
class TransportConsumer(Protocol):
    """Callback invoked by a transport worker."""

    async def __call__(
        self,
        envelope: Envelope[Message],
    ) -> ReplyEnvelope[object] | None:
        """Process one envelope and optionally return a request reply."""


@runtime_checkable
class Transport(Protocol):
    """Async request/publish delivery protocol."""

    async def start(self, consumer: TransportConsumer) -> None:
        """Start delivery to the supplied consumer."""

    async def request(
        self,
        envelope: Envelope[Message],
        *,
        timeout: float | None = None,
    ) -> ReplyEnvelope[object]:
        """Enqueue a request and await its reply."""

    async def publish(
        self,
        envelope: Envelope[Message],
        *,
        timeout: float | None = None,
    ) -> DeliveryReceipt:
        """Enqueue a one-way message and return its delivery receipt."""

    async def shutdown(self, *, timeout: float | None = None) -> None:
        """Stop accepting work and shut down the transport."""


type HandlerFunction[MessageT: Message, ResultT] = Callable[
    [MessageT, FunctionHandlerContext],
    Awaitable[ResultT],
]
