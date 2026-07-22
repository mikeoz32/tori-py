from dataclasses import dataclass

import pytest
from cqrs_core import (
    Command,
    CommandBus,
    CommandHandler,
    DuplicateCommandHandlerError,
    Event,
    EventBus,
    EventHandlerFailure,
    EventsHandler,
    MissingHandlerError,
    Query,
    QueryBus,
    QueryHandler,
)
from nestpy import (
    AliasProvider,
    ClassProvider,
    DeferredModule,
    FactoryProvider,
    ModuleSpec,
    Scope,
    module,
)
from nestpy.testing import TestingModule
from nestpy_cqrs import (
    CqrsModule,
    CqrsModuleOptions,
    command_handler,
    event_handler,
)


@dataclass(frozen=True, slots=True)
class Increment(Command[int]):
    amount: int


@dataclass(frozen=True, slots=True)
class Current(Query[int]):
    pass


@dataclass(frozen=True, slots=True)
class Incremented(Event):
    amount: int


class State:
    def __init__(self) -> None:
        self.value = 0
        self.command_constructions = 0
        self.query_constructions = 0
        self.event_constructions = 0
        self.event_deliveries = 0


@CommandHandler(Increment)
class IncrementHandler:
    def __init__(self, state: State) -> None:
        self.state = state
        state.command_constructions += 1

    async def handle(self, command: Increment) -> int:
        self.state.value += command.amount
        return self.state.value


@QueryHandler(Current)
class CurrentHandler:
    def __init__(self, state: State) -> None:
        self.state = state
        state.query_constructions += 1

    async def handle(self, query: Current) -> int:
        return self.state.value


@EventsHandler(Incremented)
class IncrementedHandler:
    def __init__(self, state: State) -> None:
        self.state = state
        state.event_constructions += 1

    async def handle(self, event: Incremented) -> None:
        self.state.event_deliveries += 1


@pytest.mark.asyncio
async def test_decorated_private_providers_are_discovered_automatically() -> None:
    @module(
        providers=[
            ClassProvider(State),
            ClassProvider(IncrementHandler, scope=Scope.REQUEST),
            ClassProvider(CurrentHandler, scope=Scope.TRANSIENT),
            ClassProvider(IncrementedHandler, scope=Scope.REQUEST),
            AliasProvider("incremented-alias", IncrementedHandler),
        ],
    )
    class Feature:
        pass

    cqrs = CqrsModule.for_root()

    @module(imports=[Feature, cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "default"))
    queries = await application.resolve(QueryBus, module=(CqrsModule, "default"))
    events = await application.resolve(EventBus, module=(CqrsModule, "default"))
    state = await application.resolve(State, module=Feature)
    assert isinstance(commands, CommandBus)
    assert isinstance(queries, QueryBus)
    assert isinstance(events, EventBus)
    assert isinstance(state, State)

    assert await commands.execute(Increment(2)) == 2
    assert await commands.execute(Increment(3)) == 5
    assert await queries.execute(Current()) == 5
    assert await queries.execute(Current()) == 5
    await events.publish(Incremented(5))
    await events.drain(timeout=1)

    assert state.command_constructions == 2
    assert state.query_constructions == 2
    assert state.event_constructions == 1
    assert state.event_deliveries == 1
    await application.close()


@pytest.mark.asyncio
async def test_discovered_duplicate_tokens_resolve_the_exact_owner_module() -> None:
    deliveries: list[str] = []

    @EventsHandler(Incremented)
    class FirstHandler:
        async def handle(self, event: Incremented) -> None:
            deliveries.append("first")

    @EventsHandler(Incremented)
    class SecondHandler:
        async def handle(self, event: Incremented) -> None:
            deliveries.append("second")

    @module(
        providers=[ClassProvider("shared-handler", FirstHandler, scope=Scope.REQUEST)]
    )
    class FirstModule:
        pass

    @module(
        providers=[ClassProvider("shared-handler", SecondHandler, scope=Scope.REQUEST)]
    )
    class SecondModule:
        pass

    cqrs = CqrsModule.for_root(key="qualified")

    @module(imports=[FirstModule, SecondModule, cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    events = await application.resolve(EventBus, module=(CqrsModule, "qualified"))
    assert isinstance(events, EventBus)
    await events.publish(Incremented(1))
    await events.drain(timeout=1)
    assert deliveries == ["first", "second"]
    await application.close()


@pytest.mark.asyncio
async def test_distinct_discovered_command_handlers_remain_an_error() -> None:
    @CommandHandler(Increment)
    class FirstHandler:
        async def handle(self, command: Increment) -> int:
            return 1

    @CommandHandler(Increment)
    class SecondHandler:
        async def handle(self, command: Increment) -> int:
            return 2

    @module(providers=[ClassProvider(FirstHandler), ClassProvider(SecondHandler)])
    class Feature:
        pass

    cqrs = CqrsModule.for_root(key="duplicate-command")

    @module(imports=[Feature, cqrs])
    class Root:
        pass

    with pytest.raises(DuplicateCommandHandlerError, match="multiple handlers"):
        await TestingModule.create(Root).compile()


@pytest.mark.asyncio
async def test_explicit_factory_binding_suppresses_automatic_class_registration() -> (
    None
):
    @CommandHandler(Increment)
    class FactoryHandler:
        async def handle(self, command: Increment) -> int:
            return command.amount

    @module(
        providers=[FactoryProvider("factory-handler", FactoryHandler)],
        exports=["factory-handler"],
    )
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[command_handler(Increment, "factory-handler")],
        key="factory",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "factory"))
    assert isinstance(commands, CommandBus)
    assert await commands.execute(Increment(7)) == 7
    await application.close()


@pytest.mark.asyncio
async def test_explicit_class_binding_suppresses_duplicate_auto_discovery() -> None:
    deliveries = 0

    @EventsHandler(Incremented)
    class Handler:
        async def handle(self, event: Incremented) -> None:
            nonlocal deliveries
            deliveries += 1

    @module(providers=[ClassProvider(Handler)], exports=[Handler])
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[event_handler(Incremented, Handler)],
        key="explicit-class",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    events = await application.resolve(
        EventBus,
        module=(CqrsModule, "explicit-class"),
    )
    assert isinstance(events, EventBus)
    await events.publish(Incremented(1))
    await events.drain(timeout=1)
    assert deliveries == 1
    await application.close()


@pytest.mark.asyncio
async def test_keyed_dynamic_modules_keep_discovered_providers_distinct() -> None:
    deliveries = 0

    @EventsHandler(Incremented)
    class Handler:
        async def handle(self, event: Incremented) -> None:
            nonlocal deliveries
            deliveries += 1

    class DynamicFeature:
        pass

    first = DeferredModule(
        DynamicFeature,
        "first",
        lambda: ModuleSpec(providers=[ClassProvider(Handler)]),
    )
    second = DeferredModule(
        DynamicFeature,
        "second",
        lambda: ModuleSpec(providers=[ClassProvider(Handler)]),
    )
    cqrs = CqrsModule.for_root(key="dynamic")

    @module(imports=[first, second, cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    events = await application.resolve(EventBus, module=(CqrsModule, "dynamic"))
    assert isinstance(events, EventBus)
    await events.publish(Incremented(1))
    await events.drain(timeout=1)
    assert deliveries == 2
    await application.close()


@pytest.mark.asyncio
async def test_discovery_uses_testing_override_implementation_metadata() -> None:
    @CommandHandler(Increment)
    class DecoratedHandler:
        async def handle(self, command: Increment) -> int:
            return command.amount

    class UndecoratedReplacement:
        async def handle(self, command: Increment) -> int:
            return -1

    @module(
        providers=[ClassProvider(DecoratedHandler)],
        exports=[DecoratedHandler],
    )
    class Feature:
        pass

    cqrs = CqrsModule.for_root(key="override")

    @module(imports=[Feature, cqrs])
    class Root:
        pass

    builder = TestingModule.create(Root)
    builder.override_provider(DecoratedHandler, module=Feature).use_class(
        UndecoratedReplacement
    )
    application = await builder.compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "override"))
    assert isinstance(commands, CommandBus)
    with pytest.raises(MissingHandlerError):
        await commands.execute(Increment(1))
    await application.close()


@pytest.mark.asyncio
async def test_discovered_event_failure_has_module_qualified_identity() -> None:
    failures: list[EventHandlerFailure] = []

    @EventsHandler(Incremented)
    class FailingHandler:
        async def handle(self, event: Incremented) -> None:
            raise RuntimeError("failed")

    @module(providers=[ClassProvider(FailingHandler)])
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        options=CqrsModuleOptions(event_error_handler=failures.append),
        key="failure-identity",
    )

    @module(imports=[Feature, cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    events = await application.resolve(
        EventBus,
        module=(CqrsModule, "failure-identity"),
    )
    assert isinstance(events, EventBus)
    await events.publish(Incremented(1))
    await events.drain(timeout=1)
    assert len(failures) == 1
    assert "Feature" in failures[0].handler
    assert failures[0].handler.endswith("FailingHandler")
    await application.close()
