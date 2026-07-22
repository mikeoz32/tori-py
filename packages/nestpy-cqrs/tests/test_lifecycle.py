import asyncio
from dataclasses import dataclass

import pytest
from cqrs_core import (
    Command,
    CommandBus,
    CqrsBuilder,
    CqrsValidationError,
    DeliveryReceipt,
    DuplicateCommandHandlerError,
    Envelope,
    Event,
    EventBus,
    InMemoryTransport,
    Message,
    ReplyEnvelope,
    TransportConsumer,
)
from nestpy import ClassProvider, module
from nestpy.testing import TestingModule
from nestpy_cqrs import (
    CqrsConfigurationError,
    CqrsLifecycleError,
    CqrsModule,
    CqrsModuleOptions,
    command_handler,
    event_handler,
)
from nestpy_cqrs.runtime import _CqrsRuntime


class RecordingTransport:
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        fail_start: bool = False,
        fail_shutdown: bool = False,
    ) -> None:
        self.name = name
        self.events = events
        self.fail_start = fail_start
        self.fail_shutdown = fail_shutdown
        self.inner = InMemoryTransport(name=f"recording-{name}")

    async def start(self, consumer: TransportConsumer) -> None:
        self.events.append(f"start:{self.name}")
        if self.fail_start:
            raise RuntimeError(f"{self.name} failed")
        await self.inner.start(consumer)

    async def request(
        self,
        envelope: Envelope[Message],
        *,
        timeout: float | None = None,
    ) -> ReplyEnvelope[object]:
        return await self.inner.request(envelope, timeout=timeout)

    async def publish(
        self,
        envelope: Envelope[Message],
        *,
        timeout: float | None = None,
    ) -> DeliveryReceipt:
        return await self.inner.publish(envelope, timeout=timeout)

    async def shutdown(self, *, timeout: float | None = None) -> None:
        self.events.append(f"stop:{self.name}")
        if self.fail_shutdown:
            raise RuntimeError(f"{self.name} cleanup failed")
        await self.inner.shutdown(timeout=timeout)


def options_for(
    events: list[str],
    *,
    fail_query: bool = False,
) -> CqrsModuleOptions:
    return CqrsModuleOptions(
        command_transport_factory=lambda: RecordingTransport("command", events),
        query_transport_factory=lambda: RecordingTransport(
            "query",
            events,
            fail_start=fail_query,
        ),
        event_transport_factory=lambda: RecordingTransport("event", events),
    )


@pytest.mark.asyncio
async def test_bus_lifecycle_order() -> None:
    events: list[str] = []
    cqrs = CqrsModule.for_root(handlers=[], options=options_for(events))

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    assert events == ["start:event", "start:query", "start:command"]
    await application.close()
    assert events == [
        "start:event",
        "start:query",
        "start:command",
        "stop:command",
        "stop:query",
        "stop:event",
    ]


@pytest.mark.asyncio
async def test_partial_start_rolls_back_attempted_buses() -> None:
    events: list[str] = []
    cqrs = CqrsModule.for_root(
        handlers=[],
        options=options_for(events, fail_query=True),
    )

    @module(imports=[cqrs])
    class Root:
        pass

    with pytest.raises(CqrsLifecycleError, match="startup"):
        await TestingModule.create(Root).compile()
    assert events == [
        "start:event",
        "start:query",
        "stop:query",
        "stop:event",
        "stop:command",
    ]


@pytest.mark.asyncio
async def test_startup_rollback_logs_secondary_cleanup_failure(caplog) -> None:
    events: list[str] = []
    caplog.set_level("ERROR", logger="nestpy_cqrs.runtime")
    cqrs = CqrsModule.for_root(
        handlers=[],
        options=CqrsModuleOptions(
            command_transport_factory=lambda: RecordingTransport("command", events),
            query_transport_factory=lambda: RecordingTransport(
                "query", events, fail_start=True
            ),
            event_transport_factory=lambda: RecordingTransport(
                "event", events, fail_shutdown=True
            ),
        ),
    )

    @module(imports=[cqrs])
    class Root:
        pass

    with pytest.raises(CqrsLifecycleError, match="startup"):
        await TestingModule.create(Root).compile()
    assert any(
        "startup rollback cleanup failed" in record.message for record in caplog.records
    )


@pytest.mark.asyncio
async def test_transport_factory_failure_closes_acquired_transports() -> None:
    events: list[str] = []
    command = RecordingTransport("command", events)

    def query_factory() -> RecordingTransport:
        raise RuntimeError("query factory failed")

    cqrs = CqrsModule.for_root(
        handlers=[],
        options=CqrsModuleOptions(
            command_transport_factory=lambda: command,
            query_transport_factory=query_factory,
        ),
    )

    @module(imports=[cqrs])
    class Root:
        pass

    with pytest.raises(CqrsConfigurationError, match="query transport factory failed"):
        await TestingModule.create(Root).compile()
    assert events == ["stop:command"]


@pytest.mark.asyncio
async def test_transport_factory_failure_logs_secondary_cleanup_error(
    caplog,
) -> None:
    events: list[str] = []

    def query_factory() -> RecordingTransport:
        raise RuntimeError("query factory failed")

    caplog.set_level("ERROR", logger="nestpy_cqrs.runtime")
    cqrs = CqrsModule.for_root(
        handlers=[],
        options=CqrsModuleOptions(
            command_transport_factory=lambda: RecordingTransport(
                "command", events, fail_shutdown=True
            ),
            query_transport_factory=query_factory,
        ),
    )

    @module(imports=[cqrs])
    class Root:
        pass

    with pytest.raises(CqrsConfigurationError, match="query transport factory"):
        await TestingModule.create(Root).compile()
    assert events == ["stop:command"]
    assert any(
        "transport cleanup failed" in record.message for record in caplog.records
    )


@pytest.mark.asyncio
async def test_shared_transport_is_closed_once_after_builder_rejection() -> None:
    events: list[str] = []
    shared = RecordingTransport("shared", events)
    cqrs = CqrsModule.for_root(
        handlers=[],
        options=CqrsModuleOptions(
            command_transport_factory=lambda: shared,
            query_transport_factory=lambda: shared,
            event_transport_factory=lambda: shared,
        ),
    )

    @module(imports=[cqrs])
    class Root:
        pass

    with pytest.raises(CqrsValidationError, match="distinct transport"):
        await TestingModule.create(Root).compile()
    assert events == ["stop:shared"]


@pytest.mark.asyncio
async def test_quiesce_logs_ordinary_failure_before_later_cancellation(
    caplog,
) -> None:
    events: list[str] = []
    query_shutdown = asyncio.Event()

    class BlockingShutdownTransport(RecordingTransport):
        async def shutdown(self, *, timeout: float | None = None) -> None:
            del timeout
            self.events.append(f"stop:{self.name}")
            query_shutdown.set()
            await asyncio.Event().wait()

    class Context:
        def remaining(self) -> float | None:
            return None

    runtime = _CqrsRuntime(
        CqrsBuilder()
        .with_command_transport(
            RecordingTransport("command", events, fail_shutdown=True)
        )
        .with_query_transport(BlockingShutdownTransport("query", events))
        .with_event_transport(RecordingTransport("event", events))
        .build()
    )
    await runtime.on_application_bootstrap()
    caplog.set_level("ERROR", logger="nestpy_cqrs.runtime")
    quiesce = asyncio.create_task(runtime.on_application_quiesce(Context()))
    await query_shutdown.wait()
    quiesce.cancel()
    with pytest.raises(asyncio.CancelledError):
        await quiesce
    assert any(
        "quiesce failure suppressed" in record.message for record in caplog.records
    )
    await runtime.close()


@pytest.mark.asyncio
async def test_startup_cancellation_is_not_retyped() -> None:
    events: list[str] = []
    start_entered = asyncio.Event()

    class BlockingStartTransport(RecordingTransport):
        async def start(self, consumer: TransportConsumer) -> None:
            del consumer
            self.events.append(f"start:{self.name}")
            start_entered.set()
            await asyncio.Event().wait()

    cqrs = CqrsModule.for_root(
        handlers=[],
        options=CqrsModuleOptions(
            command_transport_factory=lambda: RecordingTransport("command", events),
            query_transport_factory=lambda: RecordingTransport("query", events),
            event_transport_factory=lambda: BlockingStartTransport("event", events),
        ),
    )

    @module(imports=[cqrs])
    class Root:
        pass

    startup = asyncio.create_task(TestingModule.create(Root).compile())
    await start_entered.wait()
    startup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await startup
    assert events == ["start:event", "stop:event", "stop:command", "stop:query"]


@pytest.mark.asyncio
async def test_cancellation_during_startup_rollback_is_not_retyped() -> None:
    events: list[str] = []
    shutdown_entered = asyncio.Event()

    class BlockingShutdownTransport(RecordingTransport):
        async def shutdown(self, *, timeout: float | None = None) -> None:
            del timeout
            self.events.append(f"stop:{self.name}")
            shutdown_entered.set()
            await asyncio.Event().wait()

    cqrs = CqrsModule.for_root(
        handlers=[],
        options=CqrsModuleOptions(
            command_transport_factory=lambda: RecordingTransport("command", events),
            query_transport_factory=lambda: RecordingTransport(
                "query", events, fail_start=True
            ),
            event_transport_factory=lambda: BlockingShutdownTransport("event", events),
        ),
    )

    @module(imports=[cqrs])
    class Root:
        pass

    startup = asyncio.create_task(TestingModule.create(Root).compile())
    await shutdown_entered.wait()
    startup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await startup


@pytest.mark.asyncio
async def test_builder_failure_closes_all_created_transports() -> None:
    events: list[str] = []

    class FirstHandler:
        async def handle(self, command: Blocking) -> str:
            return "first"

    class SecondHandler:
        async def handle(self, command: Blocking) -> str:
            return "second"

    @module(
        providers=[ClassProvider(FirstHandler), ClassProvider(SecondHandler)],
        exports=[FirstHandler, SecondHandler],
    )
    class Handlers:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Handlers],
        handlers=[
            command_handler(Blocking, FirstHandler),
            command_handler(Blocking, SecondHandler),
        ],
        options=options_for(events),
        key="builder-failure",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    with pytest.raises(DuplicateCommandHandlerError, match="multiple handlers"):
        await TestingModule.create(Root).compile()
    assert events == ["stop:event", "stop:query", "stop:command"]


@pytest.mark.asyncio
async def test_unrelated_bootstrap_failure_closes_unstarted_buses() -> None:
    events: list[str] = []
    cqrs = CqrsModule.for_root(handlers=[], options=options_for(events))

    @module(imports=[cqrs])
    class Root:
        async def on_application_bootstrap(self) -> None:
            raise RuntimeError("root bootstrap failed")

    with pytest.raises(RuntimeError, match="root bootstrap failed"):
        await TestingModule.create(Root).compile()
    assert events == ["stop:command", "stop:query", "stop:event"]


@dataclass(frozen=True, slots=True)
class Blocking(Command[str]):
    pass


@dataclass(frozen=True, slots=True)
class Finished(Event):
    pass


class Coordination:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.event_handled = asyncio.Event()


class BlockingHandler:
    def __init__(self, coordination: Coordination, events: EventBus) -> None:
        self.coordination = coordination
        self.events = events

    async def handle(self, command: Blocking) -> str:
        self.coordination.started.set()
        await self.coordination.release.wait()
        await self.events.publish(Finished())
        return "finished"


class FinishedHandler:
    def __init__(self, coordination: Coordination) -> None:
        self.coordination = coordination

    async def handle(self, event: Finished) -> None:
        self.coordination.event_handled.set()


@pytest.mark.asyncio
async def test_quiescing_command_can_publish_event_before_event_shutdown() -> None:
    @module(
        providers=[
            ClassProvider(Coordination),
            ClassProvider(BlockingHandler),
            ClassProvider(FinishedHandler),
        ],
        exports=[BlockingHandler, FinishedHandler],
    )
    class Handlers:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Handlers],
        handlers=[
            command_handler(Blocking, BlockingHandler),
            event_handler(Finished, FinishedHandler),
        ],
        global_=True,
    )

    @module(imports=[cqrs, Handlers])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    command_bus = await application.resolve(CommandBus)
    coordination = await application.resolve(Coordination, module=Handlers)
    assert isinstance(command_bus, CommandBus)
    assert isinstance(coordination, Coordination)

    execution = asyncio.create_task(command_bus.execute(Blocking()))
    await coordination.started.wait()
    shutdown = asyncio.create_task(application.close())
    await asyncio.sleep(0)
    coordination.release.set()

    assert await execution == "finished"
    await shutdown
    assert coordination.event_handled.is_set()
