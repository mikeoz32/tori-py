from dataclasses import dataclass
from typing import Annotated, cast

import pytest
from cqrs_core import Command, CommandBus, CommandHandler, Event
from cqrs_event_sourcing import (
    AggregateRoot,
    EventSchema,
    EventSchemaRegistry,
    EventSourcedRepository,
    EventStore,
    InMemoryEventStore,
)
from nestpy import (
    BootstrapError,
    ClassProvider,
    ModuleSpec,
    Scope,
    ValueProvider,
    module,
)
from nestpy.testing import TestingModule
from nestpy_cqrs import CqrsConfigurationError, CqrsModule
from nestpy_cqrs_event_sourcing import (
    CqrsEventSourcingModule,
    CqrsEventSourcingOptions,
    aggregate_repository,
    get_event_store_token,
    use_event_sourcing,
)


@dataclass(frozen=True, slots=True)
class Created(Event):
    value: str


class Item(AggregateRoot[int]):
    def __init__(self, item_id: int) -> None:
        super().__init__(item_id)
        self.value = ""

    def create(self, value: str) -> None:
        self.raise_event(Created(value))

    def _apply(self, event: Event) -> None:
        assert isinstance(event, Created)
        self.value = event.value


@aggregate_repository(Item, category="item")
class ItemRepo(EventSourcedRepository[int, Item]):
    pass


SCHEMAS = (
    EventSchemaRegistry()
    .register(
        EventSchema(
            "item.created",
            1,
            Created,
            lambda event: event.value.encode(),
            lambda payload: Created(payload.decode()),
        )
    )
    .freeze()
)


class StoreOne(InMemoryEventStore):
    pass


class StoreTwo(InMemoryEventStore):
    pass


@dataclass(frozen=True, slots=True)
class CreateOne(Command[str]):
    value: str


@dataclass(frozen=True, slots=True)
class CreateTwo(Command[str]):
    value: str


@pytest.mark.asyncio
async def test_multiple_keyed_roots_keep_stores_and_repositories_isolated() -> None:
    @module(providers=[ClassProvider(StoreOne)], exports=[StoreOne])
    class PersistenceOne:
        pass

    @module(providers=[ClassProvider(StoreTwo)], exports=[StoreTwo])
    class PersistenceTwo:
        pass

    first_root = CqrsEventSourcingModule.for_root(
        CqrsEventSourcingOptions(store=StoreOne, schemas=SCHEMAS),
        imports=[PersistenceOne],
        key="one",
    )
    second_root = CqrsEventSourcingModule.for_root(
        CqrsEventSourcingOptions(store=StoreTwo, schemas=SCHEMAS),
        imports=[PersistenceTwo],
        key="two",
    )
    first_feature = CqrsEventSourcingModule.for_feature(
        [ItemRepo],
        root_key="one",
        key="one-feature",
    )
    second_feature = CqrsEventSourcingModule.for_feature(
        [ItemRepo],
        root_key="two",
        key="two-feature",
    )

    @use_event_sourcing(key="one")
    @CommandHandler(CreateOne)
    class FirstHandler:
        def __init__(
            self,
            items: Annotated[ItemRepo, aggregate_repository(ItemRepo)],
        ) -> None:
            self.items = items

        async def handle(self, command: CreateOne) -> str:
            item = Item(1)
            item.create(command.value)
            self.items.save(item)
            return item.value

    @use_event_sourcing(key="two")
    @CommandHandler(CreateTwo)
    class SecondHandler:
        def __init__(
            self,
            items: Annotated[ItemRepo, aggregate_repository(ItemRepo)],
        ) -> None:
            self.items = items

        async def handle(self, command: CreateTwo) -> str:
            item = Item(1)
            item.create(command.value)
            self.items.save(item)
            return item.value

    @module(
        imports=[first_feature],
        providers=[ClassProvider(FirstHandler, scope=Scope.REQUEST)],
        exports=[FirstHandler],
    )
    class FirstHandlers:
        pass

    @module(
        imports=[second_feature],
        providers=[ClassProvider(SecondHandler, scope=Scope.REQUEST)],
        exports=[SecondHandler],
    )
    class SecondHandlers:
        pass

    cqrs = CqrsModule.for_root(
        imports=[FirstHandlers, SecondHandlers],
        key="multiple",
    )

    @module(imports=[first_root, second_root, cqrs])
    class App:
        pass

    application = await TestingModule.create(App).compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "multiple"))
    assert isinstance(commands, CommandBus)
    assert await commands.execute(CreateOne("first")) == "first"
    assert await commands.execute(CreateTwo("second")) == "second"

    first_store = await application.resolve(
        get_event_store_token(key="one"),
        module=(first_root.module, first_root.key),
    )
    second_store = await application.resolve(
        get_event_store_token(key="two"),
        module=(second_root.module, second_root.key),
    )
    assert isinstance(first_store, StoreOne)
    assert isinstance(second_store, StoreTwo)
    assert first_store is not second_store
    assert len(await first_store.read_all(limit=10)) == 1
    assert len(await second_store.read_all(limit=10)) == 1
    await application.close()


@pytest.mark.asyncio
async def test_keyed_store_can_be_overridden_on_exact_root_descriptor() -> None:
    @dataclass(frozen=True, slots=True)
    class Noop(Command[None]):
        pass

    @use_event_sourcing(key="override")
    @CommandHandler(Noop)
    class Handler:
        async def handle(self, command: Noop) -> None:
            del command

    replacement = InMemoryEventStore()

    @module(providers=[ClassProvider(StoreOne)], exports=[StoreOne])
    class Persistence:
        pass

    root = CqrsEventSourcingModule.for_root(
        CqrsEventSourcingOptions(store=StoreOne, schemas=SCHEMAS),
        imports=[Persistence],
        key="override",
    )

    @module(
        providers=[ClassProvider(Handler, scope=Scope.REQUEST)],
        exports=[Handler],
    )
    class Handlers:
        pass

    cqrs = CqrsModule.for_root(imports=[Handlers], key="override")

    @module(imports=[root, cqrs])
    class App:
        pass

    builder = TestingModule.create(App)
    builder.override_provider(
        get_event_store_token(key="override"), module=root
    ).use_value(replacement)
    application = await builder.compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "override"))
    assert isinstance(commands, CommandBus)
    await commands.execute(Noop())
    resolved = await application.resolve(
        get_event_store_token(key="override"),
        module=(root.module, root.key),
    )
    assert resolved is replacement
    await application.close()


@pytest.mark.asyncio
async def test_event_store_self_token_does_not_create_alias_cycle() -> None:
    @dataclass(frozen=True, slots=True)
    class Noop(Command[None]):
        pass

    @use_event_sourcing(key="self-token")
    @CommandHandler(Noop)
    class Handler:
        async def handle(self, command: Noop) -> None:
            del command

    store = InMemoryEventStore()

    @module(providers=[ValueProvider(EventStore, store)], exports=[EventStore])
    class Persistence:
        pass

    root = CqrsEventSourcingModule.for_root(
        CqrsEventSourcingOptions(store=EventStore, schemas=SCHEMAS),
        imports=[Persistence],
        key="self-token",
    )

    @module(
        providers=[ClassProvider(Handler, scope=Scope.REQUEST)],
        exports=[Handler],
    )
    class Handlers:
        pass

    cqrs = CqrsModule.for_root(imports=[Handlers], key="self-token")

    @module(imports=[root, cqrs])
    class App:
        pass

    application = await TestingModule.create(App).compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "self-token"))
    assert isinstance(commands, CommandBus)
    await commands.execute(Noop())
    resolved = await application.resolve(
        get_event_store_token(key="self-token"),
        module=(root.module, root.key),
    )
    assert resolved is store
    await application.close()


@pytest.mark.asyncio
async def test_independent_feature_modules_share_one_global_keyed_root() -> None:
    class OtherItem(AggregateRoot[int]):
        def _apply(self, event: Event) -> None:
            del event

    @aggregate_repository(OtherItem, category="other-item")
    class OtherItemRepo(EventSourcedRepository[int, OtherItem]):
        pass

    @module(providers=[ClassProvider(StoreOne)], exports=[StoreOne])
    class Persistence:
        pass

    root = CqrsEventSourcingModule.for_root(
        CqrsEventSourcingOptions(store=StoreOne, schemas=SCHEMAS),
        imports=[Persistence],
        key="shared",
    )
    items = CqrsEventSourcingModule.for_feature([ItemRepo], root_key="shared")
    duplicate_items = CqrsEventSourcingModule.for_feature(
        [ItemRepo],
        root_key="shared",
    )
    other_items = CqrsEventSourcingModule.for_feature(
        [OtherItemRepo],
        root_key="shared",
    )
    assert items.module is not duplicate_items.module
    assert items.module is not other_items.module
    assert cast(ModuleSpec, items.factory()).imports == ()

    @module(imports=[items])
    class ItemsModule:
        pass

    @module(imports=[other_items])
    class OtherItemsModule:
        pass

    @module(imports=[duplicate_items])
    class DuplicateItemsModule:
        pass

    @module(imports=[root, ItemsModule, OtherItemsModule, DuplicateItemsModule])
    class App:
        pass

    replacement = object()
    builder = TestingModule.create(App)
    builder.override_provider(ItemRepo, module=items).use_value(replacement)
    application = await builder.compile()
    resolved = await application.resolve(
        ItemRepo,
        module=(items.module, items.key),
    )
    assert resolved is replacement
    await application.close()


@pytest.mark.asyncio
async def test_feature_without_selected_root_fails_graph_compilation() -> None:
    feature = CqrsEventSourcingModule.for_feature(
        [ItemRepo],
        root_key="missing",
    )

    @module(imports=[feature])
    class FeatureModule:
        pass

    @module(imports=[FeatureModule])
    class App:
        pass

    with pytest.raises(BootstrapError) as failure:
        await TestingModule.create(App).compile()
    assert failure.value.diagnostic_code == "provider.unresolved"


@pytest.mark.asyncio
async def test_transactional_handler_without_root_fails_before_dispatch() -> None:
    @dataclass(frozen=True, slots=True)
    class Noop(Command[None]):
        pass

    @use_event_sourcing(key="missing-handler-root")
    @CommandHandler(Noop)
    class Handler:
        async def handle(self, command: Noop) -> None:
            del command

    @module(providers=[ClassProvider(Handler)], exports=[Handler])
    class Handlers:
        pass

    cqrs = CqrsModule.for_root(imports=[Handlers], key="missing-handler-root")

    @module(imports=[cqrs])
    class App:
        pass

    with pytest.raises(CqrsConfigurationError, match="not visible"):
        await TestingModule.create(App).compile()


@pytest.mark.asyncio
async def test_root_can_reexport_its_prekeyed_store_token() -> None:
    key = "prekeyed"
    store_token = get_event_store_token(key=key)
    store = InMemoryEventStore()

    @module(providers=[ValueProvider(store_token, store)], exports=[store_token])
    class Persistence:
        pass

    root = CqrsEventSourcingModule.for_root(
        CqrsEventSourcingOptions(store=store_token, schemas=SCHEMAS),
        imports=[Persistence],
        key=key,
    )

    @module(imports=[root])
    class App:
        pass

    application = await TestingModule.create(App).compile()
    resolved = await application.resolve(
        store_token,
        module=(root.module, root.key),
    )
    assert resolved is store
    await application.close()
