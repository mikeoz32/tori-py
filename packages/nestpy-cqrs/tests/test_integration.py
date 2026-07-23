import asyncio
import contextvars
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from cqrs_core import (
    Command,
    CommandBus,
    Event,
    EventBus,
    EventHandlerFailure,
    Query,
    QueryBus,
)
from nestpy import (
    BootstrapError,
    ClassProvider,
    FactoryProvider,
    Scope,
    module,
)
from nestpy.testing import TestingModule
from nestpy_cqrs import (
    CqrsConfigurationError,
    CqrsModule,
    CqrsModuleOptions,
    bind_command_handler,
    bind_event_handler,
    bind_query_handler,
)

ambient: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "nestpy_cqrs_test_ambient",
    default=None,
)


@dataclass(frozen=True, slots=True)
class Add(Command[int]):
    value: int


@dataclass(frozen=True, slots=True)
class Total(Query[int]):
    pass


@dataclass(frozen=True, slots=True)
class Added(Event):
    value: int


@dataclass(frozen=True, slots=True)
class Fail(Command[None]):
    pass


@dataclass(frozen=True, slots=True)
class Identify(Command[int]):
    pass


class Tracker:
    def __init__(self) -> None:
        self.values: list[int] = []
        self.handler_ids: list[int] = []
        self.command_handler_ids: list[int] = []
        self.identify_handler_constructions = 0
        self.resource_entries = 0
        self.resource_exits = 0


class RequestResource:
    def __init__(self, identity: int) -> None:
        self.identity = identity


def request_resource(tracker: Tracker):
    @asynccontextmanager
    async def resource() -> AsyncIterator[RequestResource]:
        tracker.resource_entries += 1
        try:
            yield RequestResource(tracker.resource_entries)
        finally:
            tracker.resource_exits += 1

    return resource()


class AddHandler:
    def __init__(
        self,
        tracker: Tracker,
        resource: RequestResource,
        events: EventBus,
    ) -> None:
        self.tracker = tracker
        self.resource = resource
        self.events = events

    async def handle(self, command: Add) -> int:
        assert ambient.get() is None
        self.tracker.command_handler_ids.append(id(self))
        await self.events.publish(Added(command.value))
        return self.resource.identity


class TotalHandler:
    def __init__(self, tracker: Tracker) -> None:
        self.tracker = tracker

    async def handle(self, query: Total) -> int:
        assert ambient.get() is None
        return sum(self.tracker.values)


class RecordAdded:
    def __init__(self, tracker: Tracker, resource: RequestResource) -> None:
        self.tracker = tracker
        self.resource = resource

    async def handle(self, event: Added) -> None:
        assert ambient.get() is None
        self.tracker.values.append(event.value)
        self.tracker.handler_ids.append(id(self))


class AuditAdded:
    def __init__(self, tracker: Tracker, resource: RequestResource) -> None:
        self.tracker = tracker
        self.resource = resource

    async def handle(self, event: Added) -> None:
        assert ambient.get() is None
        self.tracker.handler_ids.append(id(self))


class FailHandler:
    def __init__(self, resource: RequestResource) -> None:
        self.resource = resource

    async def handle(self, command: Fail) -> None:
        raise RuntimeError("handler failed")


class IdentifyHandler:
    def __init__(self, tracker: Tracker) -> None:
        self.tracker = tracker
        tracker.identify_handler_constructions += 1

    async def handle(self, command: Identify) -> int:
        return self.tracker.identify_handler_constructions


@module(
    providers=[
        ClassProvider(Tracker),
        FactoryProvider(
            RequestResource,
            request_resource,
            scope=Scope.REQUEST,
        ),
        ClassProvider(AddHandler, scope=Scope.REQUEST),
        ClassProvider(TotalHandler, scope=Scope.TRANSIENT),
        ClassProvider(RecordAdded, scope=Scope.REQUEST),
        ClassProvider(AuditAdded, scope=Scope.TRANSIENT),
        ClassProvider(FailHandler, scope=Scope.REQUEST),
        ClassProvider(IdentifyHandler),
    ],
    exports=[
        AddHandler,
        TotalHandler,
        RecordAdded,
        AuditAdded,
        FailHandler,
        IdentifyHandler,
    ],
)
class HandlersModule:
    pass


cqrs = CqrsModule.for_root(
    imports=[HandlersModule],
    handlers=[
        bind_command_handler(Add, AddHandler),
        bind_command_handler(Fail, FailHandler),
        bind_command_handler(Identify, IdentifyHandler),
        bind_query_handler(Total, TotalHandler),
        bind_event_handler(Added, RecordAdded),
        bind_event_handler(Added, AuditAdded),
    ],
    global_=True,
)


@module(imports=[cqrs])
class AppModule:
    pass


@pytest.mark.asyncio
async def test_scoped_dispatch_and_event_fanout() -> None:
    application = await TestingModule.create(AppModule).compile()
    command_bus = await application.resolve(CommandBus)
    query_bus = await application.resolve(QueryBus)
    event_bus = await application.resolve(EventBus)
    tracker = await application.resolve(Tracker, module=HandlersModule)
    assert isinstance(command_bus, CommandBus)
    assert isinstance(query_bus, QueryBus)
    assert isinstance(event_bus, EventBus)
    assert isinstance(tracker, Tracker)

    token = ambient.set("http-request")
    try:
        first_resource = await command_bus.execute(Add(2))
        second_resource = await command_bus.execute(Add(3))
        await event_bus.drain(timeout=1)
        total = await query_bus.execute(Total())
    finally:
        ambient.reset(token)

    assert first_resource != second_resource
    assert total == 5
    assert tracker.values == [2, 3]
    assert tracker.resource_entries == 6
    assert tracker.resource_exits == 6
    assert len(set(tracker.command_handler_ids)) == 2
    await application.close()


@pytest.mark.asyncio
async def test_handler_failure_still_closes_work_scope() -> None:
    application = await TestingModule.create(AppModule).compile()
    command_bus = await application.resolve(CommandBus)
    tracker = await application.resolve(Tracker, module=HandlersModule)
    assert isinstance(command_bus, CommandBus)
    assert isinstance(tracker, Tracker)
    before = tracker.resource_exits
    with pytest.raises(RuntimeError, match="handler failed"):
        await command_bus.execute(Fail())
    assert tracker.resource_exits == before + 1
    await application.close()


@pytest.mark.asyncio
async def test_singleton_handler_is_reused_across_work_scopes() -> None:
    application = await TestingModule.create(AppModule).compile()
    command_bus = await application.resolve(CommandBus)
    assert isinstance(command_bus, CommandBus)

    first = await command_bus.execute(Identify())
    second = await command_bus.execute(Identify())
    tracker = await application.resolve(Tracker, module=HandlersModule)
    assert isinstance(tracker, Tracker)
    assert (first, second) == (1, 1)
    assert tracker.identify_handler_constructions == 1
    await application.close()


@pytest.mark.asyncio
async def test_cancelled_event_handler_closes_its_work_scope() -> None:
    started = asyncio.Event()

    class BlockingAdded:
        def __init__(self, resource: RequestResource) -> None:
            self.resource = resource

        async def handle(self, event: Added) -> None:
            started.set()
            await asyncio.Event().wait()

    @module(
        providers=[
            ClassProvider(Tracker),
            FactoryProvider(
                RequestResource,
                request_resource,
                scope=Scope.REQUEST,
            ),
            ClassProvider(BlockingAdded, scope=Scope.REQUEST),
        ],
        exports=[BlockingAdded],
    )
    class BlockingHandlers:
        pass

    blocking_cqrs = CqrsModule.for_root(
        imports=[BlockingHandlers],
        handlers=[bind_event_handler(Added, BlockingAdded)],
        key="blocking",
    )

    @module(imports=[blocking_cqrs, BlockingHandlers])
    class BlockingRoot:
        pass

    application = await TestingModule.create(BlockingRoot).compile()
    event_bus = await application.resolve(EventBus, module=(CqrsModule, "blocking"))
    tracker = await application.resolve(Tracker, module=BlockingHandlers)
    assert isinstance(event_bus, EventBus)
    assert isinstance(tracker, Tracker)

    await event_bus.publish(Added(1))
    await started.wait()
    await event_bus.drain(timeout=0)
    assert tracker.resource_entries == 1
    assert tracker.resource_exits == 1
    await application.close()


@pytest.mark.asyncio
async def test_event_failure_reports_configured_provider_identity() -> None:
    failures: list[EventHandlerFailure] = []

    class FailingAdded:
        async def handle(self, event: Added) -> None:
            raise RuntimeError("event failed")

    @module(
        providers=[ClassProvider(FailingAdded)],
        exports=[FailingAdded],
    )
    class FailingHandlers:
        pass

    failing_cqrs = CqrsModule.for_root(
        imports=[FailingHandlers],
        handlers=[bind_event_handler(Added, FailingAdded)],
        options=CqrsModuleOptions(event_error_handler=failures.append),
        key="failing",
    )

    @module(imports=[failing_cqrs])
    class FailingRoot:
        pass

    application = await TestingModule.create(FailingRoot).compile()
    event_bus = await application.resolve(EventBus, module=(CqrsModule, "failing"))
    assert isinstance(event_bus, EventBus)

    await event_bus.publish(Added(1))
    await event_bus.drain(timeout=1)
    assert len(failures) == 1
    assert failures[0].handler.endswith("FailingAdded")
    assert failures[0].handler_id == id(FailingAdded)
    await application.close()


@pytest.mark.asyncio
async def test_handler_token_must_be_exported_to_cqrs_module() -> None:
    class HiddenHandler:
        async def handle(self, command: Add) -> int:
            return command.value

    @module(providers=[ClassProvider(HiddenHandler)])
    class HiddenModule:
        pass

    hidden_cqrs = CqrsModule.for_root(
        imports=[HiddenModule],
        handlers=[bind_command_handler(Add, HiddenHandler)],
        key="hidden",
    )

    @module(imports=[hidden_cqrs])
    class HiddenRoot:
        pass

    with pytest.raises(BootstrapError, match="unresolved alias target"):
        await TestingModule.create(HiddenRoot).compile()


@pytest.mark.asyncio
async def test_sync_handler_is_rejected_before_invocation() -> None:
    calls = 0

    class SyncHandler:
        def handle(self, command: Add) -> int:
            nonlocal calls
            calls += 1
            return command.value

    @module(
        providers=[ClassProvider(SyncHandler)],
        exports=[SyncHandler],
    )
    class SyncHandlers:
        pass

    sync_cqrs = CqrsModule.for_root(
        imports=[SyncHandlers],
        handlers=[bind_command_handler(Add, SyncHandler)],
        key="sync",
    )

    @module(imports=[sync_cqrs])
    class SyncRoot:
        pass

    application = await TestingModule.create(SyncRoot).compile()
    command_bus = await application.resolve(CommandBus, module=(CqrsModule, "sync"))
    assert isinstance(command_bus, CommandBus)
    with pytest.raises(CqrsConfigurationError, match="async handle"):
        await command_bus.execute(Add(1))
    assert calls == 0
    await application.close()
