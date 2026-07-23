import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import cast

import pytest
from cqrs_core import (
    Command,
    CommandBus,
    CqrsBuilder,
    CqrsBuses,
    DeliveryReceipt,
    DispatchContext,
    Envelope,
    Event,
    HandlerContext,
    HandlerProvider,
    HandlerRegistration,
    InMemoryTransport,
    Message,
    NestedCommandDispatchError,
    Query,
    RegisteredHandler,
    ReplyEnvelope,
    TransportConsumer,
)


@dataclass(frozen=True, slots=True)
class Outer(Command[str]):
    value: str = "outer"


@dataclass(frozen=True, slots=True)
class Inner(Command[str]):
    value: str = "inner"


@dataclass(frozen=True, slots=True)
class Failing(Command[str]):
    pass


@dataclass(frozen=True, slots=True)
class Blocking(Command[str]):
    pass


@dataclass(frozen=True, slots=True)
class ReadValue(Query[str]):
    value: str


@dataclass(frozen=True, slots=True)
class Notified(Event):
    value: str


class DirectTransport:
    def __init__(self) -> None:
        self.consumer: TransportConsumer | None = None
        self.requests: list[Envelope[Message]] = []
        self.publications: list[Envelope[Message]] = []

    async def start(self, consumer: TransportConsumer) -> None:
        self.consumer = consumer

    async def request(
        self,
        envelope: Envelope[Message],
        *,
        timeout: float | None = None,
    ) -> ReplyEnvelope[object]:
        del timeout
        self.requests.append(envelope)
        assert self.consumer is not None
        reply = await self.consumer(envelope)
        assert reply is not None
        return reply

    async def publish(
        self,
        envelope: Envelope[Message],
        *,
        timeout: float | None = None,
    ) -> DeliveryReceipt:
        del timeout
        self.publications.append(envelope)
        return DeliveryReceipt(
            message_id=envelope.message_id,
            delivery_id=envelope.delivery.delivery_id,
            enqueued_at=envelope.delivery.enqueued_at,
        )

    async def shutdown(self, *, timeout: float | None = None) -> None:
        del timeout


def build_direct(
    *command_handlers: tuple[type[Message], object],
    provider: HandlerProvider[object] | None = None,
    query_handlers: tuple[tuple[type[Message], object], ...] = (),
) -> tuple[CqrsBuses, DirectTransport, DirectTransport, DirectTransport]:
    command_transport = DirectTransport()
    query_transport = DirectTransport()
    event_transport = DirectTransport()
    builder = (
        CqrsBuilder()
        .with_command_transport(command_transport)
        .with_query_transport(query_transport)
        .with_event_transport(event_transport)
    )
    for message_type, handler in command_handlers:
        builder.add_command_handler(message_type, handler)
    for message_type, handler in query_handlers:
        builder.add_query_handler(message_type, handler)
    if provider is not None:
        builder.with_handler_provider(provider)
    return (
        builder.build(),
        command_transport,
        query_transport,
        event_transport,
    )


class InnerHandler:
    def __init__(self, deliveries: list[str] | None = None) -> None:
        self._deliveries = deliveries

    async def handle(self, message: Inner) -> str:
        if self._deliveries is not None:
            self._deliveries.append(message.value)
        return message.value


@pytest.mark.asyncio
async def test_class_handler_rejects_same_bus_before_transport_request() -> None:
    class OuterHandler:
        bus: CommandBus | None = None

        async def handle(self, message: Outer) -> str:
            assert self.bus is not None
            return await self.bus.execute(Inner(value=message.value))

    outer_handler = OuterHandler()
    buses, command_transport, _, _ = build_direct(
        (Outer, outer_handler),
        (Inner, InnerHandler()),
    )
    outer_handler.bus = buses.command_bus
    await buses.command_bus.start()

    with pytest.raises(NestedCommandDispatchError, match="active CommandBus"):
        await buses.command_bus.execute(Outer())

    assert [type(item.message) for item in command_transport.requests] == [Outer]


@pytest.mark.asyncio
async def test_function_handler_rejects_same_bus_before_transport_request() -> None:
    async def outer_handler(message: Outer, context: HandlerContext) -> str:
        return cast(
            str,
            await context.command_bus.execute(Inner(value=message.value)),
        )

    buses, command_transport, _, _ = build_direct(
        (Outer, outer_handler),
        (Inner, InnerHandler()),
    )
    await buses.command_bus.start()

    with pytest.raises(NestedCommandDispatchError):
        await buses.command_bus.execute(Outer())

    assert [type(item.message) for item in command_transport.requests] == [Outer]


@pytest.mark.asyncio
async def test_provider_scope_observes_active_command_bus() -> None:
    class ReentrancyCheckingProvider:
        def __init__(self) -> None:
            self.rejected = False

        def provide(
            self,
            registration: HandlerRegistration,
            context: DispatchContext,
        ) -> AbstractAsyncContextManager[object]:
            registered = cast(RegisteredHandler, registration)
            handler_context = cast(HandlerContext, context)

            @asynccontextmanager
            async def scope() -> AsyncIterator[object]:
                if registration.message_type is Outer:
                    with pytest.raises(NestedCommandDispatchError):
                        await handler_context.command_bus.execute(Inner())
                    self.rejected = True
                yield registered.target

            return scope()

    class OuterHandler:
        async def handle(self, message: Outer) -> str:
            return message.value

    provider = ReentrancyCheckingProvider()
    buses, command_transport, _, _ = build_direct(
        (Outer, OuterHandler()),
        (Inner, InnerHandler()),
        provider=provider,
    )
    await buses.command_bus.start()

    assert await buses.command_bus.execute(Outer()) == "outer"
    assert provider.rejected
    assert [type(item.message) for item in command_transport.requests] == [Outer]


@pytest.mark.asyncio
async def test_different_command_buses_execute_independently() -> None:
    class OuterHandler:
        bus: CommandBus | None = None

        async def handle(self, message: Outer) -> str:
            assert self.bus is not None
            return await self.bus.execute(Inner(value=message.value))

    outer_handler = OuterHandler()
    outer_buses, outer_transport, _, _ = build_direct((Outer, outer_handler))
    inner_buses, inner_transport, _, _ = build_direct((Inner, InnerHandler()))
    outer_handler.bus = inner_buses.command_bus
    await outer_buses.command_bus.start()
    await inner_buses.command_bus.start()

    assert await outer_buses.command_bus.execute(Outer(value="ok")) == "ok"
    assert [type(item.message) for item in outer_transport.requests] == [Outer]
    assert [type(item.message) for item in inner_transport.requests] == [Inner]


@pytest.mark.asyncio
async def test_queries_and_events_remain_available_in_command_handlers() -> None:
    async def outer_handler(message: Outer, context: HandlerContext) -> str:
        result = await context.query_bus.execute(ReadValue(value=message.value))
        await context.event_bus.publish(Notified(value=cast(str, result)))
        return cast(str, result)

    class ReadHandler:
        async def handle(self, query: ReadValue) -> str:
            return query.value

    buses, _, query_transport, event_transport = build_direct(
        (Outer, outer_handler),
        query_handlers=((ReadValue, ReadHandler()),),
    )
    await buses.command_bus.start()
    await buses.query_bus.start()
    await buses.event_bus.start()

    assert await buses.command_bus.execute(Outer(value="ok")) == "ok"
    assert [type(item.message) for item in query_transport.requests] == [ReadValue]
    assert [type(item.message) for item in event_transport.publications] == [Notified]


@pytest.mark.asyncio
async def test_handler_failure_clears_active_bus_context() -> None:
    class FailingHandler:
        async def handle(self, message: Failing) -> str:
            del message
            raise RuntimeError("failed")

    buses = (
        CqrsBuilder()
        .add_command_handler(Failing, FailingHandler())
        .add_command_handler(Inner, InnerHandler())
        .with_command_transport(InMemoryTransport(name="failure-command"))
        .with_query_transport(InMemoryTransport(name="failure-query"))
        .with_event_transport(InMemoryTransport(name="failure-event"))
        .build()
    )
    await buses.command_bus.start()

    with pytest.raises(RuntimeError, match="failed"):
        await buses.command_bus.execute(Failing())

    assert await buses.command_bus.execute(Inner(value="after failure")) == (
        "after failure"
    )
    await buses.command_bus.shutdown()


@pytest.mark.asyncio
async def test_handler_cancellation_clears_active_bus_context() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingHandler:
        async def handle(self, message: Blocking) -> str:
            del message
            started.set()
            await release.wait()
            return "released"

    buses, command_transport, _, _ = build_direct(
        (Blocking, BlockingHandler()),
        (Inner, InnerHandler()),
    )
    await buses.command_bus.start()
    operation = asyncio.create_task(buses.command_bus.execute(Blocking()))
    await started.wait()

    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation

    assert await buses.command_bus.execute(Inner(value="after cancellation")) == (
        "after cancellation"
    )
    assert [type(item.message) for item in command_transport.requests] == [
        Blocking,
        Inner,
    ]


@pytest.mark.asyncio
async def test_retained_child_task_can_dispatch_after_handler_completion() -> None:
    release_child = asyncio.Event()
    child_tasks: list[asyncio.Task[object]] = []

    async def outer_handler(message: Outer, context: HandlerContext) -> str:
        async def dispatch_later() -> object:
            await release_child.wait()
            return await context.command_bus.execute(Inner(value=message.value))

        child_tasks.append(asyncio.create_task(dispatch_later()))
        return message.value

    buses, command_transport, _, _ = build_direct(
        (Outer, outer_handler),
        (Inner, InnerHandler()),
    )
    await buses.command_bus.start()

    assert await buses.command_bus.execute(Outer(value="later")) == "later"
    release_child.set()
    assert await child_tasks[0] == "later"
    assert [type(item.message) for item in command_transport.requests] == [Outer, Inner]


@pytest.mark.asyncio
async def test_timeout_wrapped_rejection_is_never_delivered_later() -> None:
    nested_errors: list[BaseException] = []
    inner_deliveries: list[str] = []

    async def outer_handler(message: Outer, context: HandlerContext) -> str:
        try:
            async with asyncio.timeout(0.01):
                await context.command_bus.execute(Inner(value=message.value))
        except BaseException as error:
            nested_errors.append(error)
        return message.value

    command_transport = InMemoryTransport(name="reentrancy-command")
    buses = (
        CqrsBuilder()
        .add_command_handler(Outer, outer_handler)
        .add_command_handler(Inner, InnerHandler(inner_deliveries))
        .with_command_transport(command_transport)
        .with_query_transport(InMemoryTransport(name="reentrancy-query"))
        .with_event_transport(InMemoryTransport(name="reentrancy-event"))
        .build()
    )
    await buses.command_bus.start()

    assert await buses.command_bus.execute(Outer(value="never")) == "never"
    await asyncio.sleep(0.02)

    assert len(nested_errors) == 1
    assert isinstance(nested_errors[0], NestedCommandDispatchError)
    assert inner_deliveries == []
    await buses.command_bus.shutdown()


@pytest.mark.asyncio
async def test_concurrent_top_level_commands_remain_supported() -> None:
    class YieldingHandler:
        async def handle(self, message: Inner) -> str:
            await asyncio.sleep(0)
            return message.value

    command_transport = InMemoryTransport(name="concurrent-command")
    buses = (
        CqrsBuilder()
        .add_command_handler(Inner, YieldingHandler())
        .with_command_transport(command_transport)
        .with_query_transport(InMemoryTransport(name="concurrent-query"))
        .with_event_transport(InMemoryTransport(name="concurrent-event"))
        .build()
    )
    await buses.command_bus.start()

    first = asyncio.create_task(buses.command_bus.execute(Inner(value="first")))
    second = asyncio.create_task(buses.command_bus.execute(Inner(value="second")))

    assert await asyncio.gather(first, second) == ["first", "second"]
    await buses.command_bus.shutdown()
