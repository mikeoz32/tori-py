import asyncio
import logging
from dataclasses import dataclass

import pytest
from tori_py_cqrs_core import (
    CqrsBuilder,
    Event,
    EventBus,
    EventErrorHandler,
    EventHandlerFailure,
    EventsHandler,
    InMemoryTransport,
    TransportStoppedError,
    message_type_for,
)


@dataclass(frozen=True, slots=True)
class UserRegistered(Event):
    user_id: int


@EventsHandler(UserRegistered)
class BlockingHandler:
    def __init__(self, started: asyncio.Event, release: asyncio.Event) -> None:
        self.started = started
        self.release = release
        self.cancelled = asyncio.Event()

    async def handle(self, message: UserRegistered) -> None:
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


@EventsHandler(UserRegistered)
class FailingHandler:
    async def handle(self, message: UserRegistered) -> None:
        raise RuntimeError(f"failed user {message.user_id}")


@EventsHandler(UserRegistered)
class StartedHandler:
    def __init__(self, started: asyncio.Event) -> None:
        self.started = started

    async def handle(self, message: UserRegistered) -> None:
        self.started.set()


async def start_event_bus(
    *handlers: object,
    error_handler: EventErrorHandler | None = None,
) -> tuple[EventBus, InMemoryTransport]:
    event_transport = InMemoryTransport(name="event-test")
    buses = (
        CqrsBuilder()
        .with_command_transport(InMemoryTransport(name="command-test"))
        .with_query_transport(InMemoryTransport(name="query-test"))
        .with_event_transport(event_transport)
    )
    for handler in handlers:
        buses.add_event_handler(handler)
    if error_handler is not None:
        buses.with_event_error_handler(error_handler)
    built = buses.build()
    await built.event_bus.start()
    return built.event_bus, event_transport


@pytest.mark.asyncio
async def test_publish_returns_before_handler_finishes_and_drain_removes_task() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    handler = BlockingHandler(started, release)
    event_bus, transport = await start_event_bus(handler)

    try:
        receipt = await asyncio.wait_for(
            event_bus.publish(UserRegistered(user_id=1)),
            timeout=0.1,
        )
        await started.wait()
        assert receipt.message_id
        assert event_bus._event_tasks
        assert not release.is_set()

        release.set()
        await event_bus.drain()
        assert event_bus._event_tasks == set()
    finally:
        release.set()
        await event_bus.shutdown(timeout=1)
        assert transport.state.value == "stopped"


@pytest.mark.asyncio
async def test_matching_handlers_run_concurrently_and_are_all_tracked() -> None:
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release = asyncio.Event()

    @EventsHandler(UserRegistered)
    class FirstHandler:
        async def handle(self, message: UserRegistered) -> None:
            first_started.set()
            await release.wait()

    @EventsHandler(UserRegistered)
    class SecondHandler:
        async def handle(self, message: UserRegistered) -> None:
            second_started.set()
            await release.wait()

    event_bus, _ = await start_event_bus(FirstHandler, SecondHandler)
    try:
        await event_bus.publish(UserRegistered(user_id=2))
        await asyncio.gather(first_started.wait(), second_started.wait())
        assert len(event_bus._event_tasks) == 2
        release.set()
        await event_bus.drain()
        assert event_bus._event_tasks == set()
    finally:
        release.set()
        await event_bus.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_failed_event_handler_calls_sync_error_hook_without_failing_publish() -> (
    None
):
    failures: list[EventHandlerFailure] = []

    def error_hook(failure: EventHandlerFailure) -> None:
        failures.append(failure)

    event_bus, _ = await start_event_bus(FailingHandler(), error_handler=error_hook)
    try:
        receipt = await event_bus.publish(UserRegistered(user_id=3))
        await event_bus.drain()

        assert len(failures) == 1
        assert failures[0].message_id == receipt.message_id
        assert failures[0].event_type == message_type_for(UserRegistered)
        assert failures[0].handler.endswith("FailingHandler")
        assert isinstance(failures[0].error, RuntimeError)
    finally:
        await event_bus.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_error_hook_failure_is_logged_and_contained(caplog) -> None:
    caplog.set_level(logging.ERROR, logger="tori_py_cqrs_core.buses")

    async def error_hook(failure: EventHandlerFailure) -> None:
        raise RuntimeError("error hook failure")

    event_bus, _ = await start_event_bus(FailingHandler(), error_handler=error_hook)
    try:
        await event_bus.publish(UserRegistered(user_id=4))
        await event_bus.drain()
        assert any(
            "Event error handler failed" in record.message for record in caplog.records
        )
    finally:
        await event_bus.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_drain_timeout_cancels_error_observer_created_by_failed_handler() -> None:
    hook_started = asyncio.Event()
    hook_release = asyncio.Event()

    async def error_hook(failure: EventHandlerFailure) -> None:
        hook_started.set()
        await hook_release.wait()

    event_bus, _ = await start_event_bus(FailingHandler(), error_handler=error_hook)
    try:
        await event_bus.publish(UserRegistered(user_id=41))
        await hook_started.wait()
        await event_bus.drain(timeout=0)
        assert event_bus._event_tasks == set()
    finally:
        hook_release.set()
        await event_bus.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_drain_timeout_cancels_remaining_event_handlers() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    handler = BlockingHandler(started, release)
    event_bus, _ = await start_event_bus(handler)

    try:
        await event_bus.publish(UserRegistered(user_id=5))
        await started.wait()
        await event_bus.drain(timeout=0)

        assert handler.cancelled.is_set()
        assert event_bus._event_tasks == set()
    finally:
        release.set()
        await event_bus.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_shutdown_drains_event_handlers_and_does_not_leave_tasks() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    handler = BlockingHandler(started, release)
    event_bus, transport = await start_event_bus(handler)

    await event_bus.publish(UserRegistered(user_id=6))
    await started.wait()
    release.set()
    await event_bus.shutdown(timeout=1)

    assert transport.state.value == "stopped"
    assert event_bus._event_tasks == set()


@pytest.mark.asyncio
async def test_concurrent_shutdown_waits_for_the_first_shutdown() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    handler = BlockingHandler(started, release)
    event_bus, _ = await start_event_bus(handler)

    await event_bus.publish(UserRegistered(user_id=61))
    await started.wait()
    first_shutdown = asyncio.create_task(event_bus.shutdown())
    await asyncio.sleep(0)
    second_shutdown = asyncio.create_task(event_bus.shutdown(timeout=0))
    await asyncio.sleep(0)
    assert not second_shutdown.done()

    await first_shutdown
    await second_shutdown
    assert handler.cancelled.is_set()
    assert event_bus._event_tasks == set()


@pytest.mark.asyncio
async def test_forced_concurrent_shutdown_wakes_unbounded_event_drain() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    @EventsHandler(UserRegistered)
    class CancellationResistantHandler:
        async def handle(self, message: UserRegistered) -> None:
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()

    event_bus, _ = await start_event_bus(CancellationResistantHandler)
    await event_bus.publish(UserRegistered(user_id=62))
    await started.wait()
    first_shutdown = asyncio.create_task(event_bus.shutdown())
    await asyncio.sleep(0)
    second_shutdown = asyncio.create_task(event_bus.shutdown(timeout=0))

    await second_shutdown
    await first_shutdown
    release.set()
    await event_bus.drain(timeout=1)
    assert event_bus._event_tasks == set()


@pytest.mark.asyncio
async def test_shutdown_during_start_does_not_resurrect_the_bus() -> None:
    class BlockingStartTransport(InMemoryTransport):
        def __init__(self) -> None:
            super().__init__(name="blocking-start")
            self.start_called = asyncio.Event()
            self.allow_start = asyncio.Event()

        async def start(self, consumer) -> None:
            self.start_called.set()
            await self.allow_start.wait()
            await super().start(consumer)

    transport = BlockingStartTransport()
    buses = (
        CqrsBuilder()
        .with_command_transport(InMemoryTransport(name="command-start"))
        .with_query_transport(InMemoryTransport(name="query-start"))
        .with_event_transport(transport)
        .build()
    )
    start = asyncio.create_task(buses.event_bus.start())
    await transport.start_called.wait()
    shutdown = asyncio.create_task(buses.event_bus.shutdown(timeout=0))
    await shutdown
    assert not start.done()
    transport.allow_start.set()

    with pytest.raises(TransportStoppedError):
        await start
    assert transport.state.value == "stopped"


@pytest.mark.asyncio
async def test_event_handler_failure_does_not_kill_transport_worker() -> None:
    started = asyncio.Event()
    event_bus, _ = await start_event_bus(FailingHandler(), StartedHandler(started))

    try:
        await event_bus.publish(UserRegistered(user_id=7))
        await event_bus.publish(UserRegistered(user_id=8))
        await started.wait()
        await event_bus.drain()
        assert event_bus._event_tasks == set()
    finally:
        await event_bus.shutdown(timeout=1)
