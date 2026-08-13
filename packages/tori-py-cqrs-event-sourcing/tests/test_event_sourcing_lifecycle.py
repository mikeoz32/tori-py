import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

import pytest
from tori_py import ClassProvider, FactoryProvider, Inject, Scope, module
from tori_py.testing import TestingModule
from tori_py_cqrs import (
    CqrsConfigurationError,
    CqrsInvocationContext,
    CqrsModule,
    bind_query_handler,
    use_cqrs_interceptors,
)
from tori_py_cqrs_core import (
    Command,
    CommandBus,
    CommandHandler,
    Event,
    EventBus,
    EventsHandler,
    Query,
    QueryBus,
    QueryHandler,
)
from tori_py_cqrs_event_sourcing import (
    CommandCancellationError,
    CommandTransactionUnavailableError,
    ConfirmedCommandFinalizationError,
    ConfirmedNonCommitFinalizationError,
    CqrsEventSourcingModule,
    CqrsEventSourcingOptions,
    aggregate_repository,
    event_sourcing_transaction,
    get_event_store_token,
    use_event_sourcing,
)
from tori_py_cqrs_event_sourcing_core import (
    AggregateRoot,
    ConfirmedNonCommit,
    EventSchema,
    EventSchemaRegistry,
    EventSourcedRepository,
    EventSourcingUnitOfWork,
    EventStore,
    InMemoryEventStore,
)


@dataclass(frozen=True, slots=True)
class MemberOpened(Event):
    name: str


class Member(AggregateRoot[int]):
    def __init__(self, member_id: int) -> None:
        super().__init__(member_id)
        self.name = ""

    def open(self, name: str) -> None:
        self.raise_event(MemberOpened(name))

    def _apply(self, event: Event) -> None:
        assert isinstance(event, MemberOpened)
        self.name = event.name


@aggregate_repository(Member, category="member")
class MemberRepo(EventSourcedRepository[int, Member]):
    async def named(self, member_id: int) -> str | None:
        member = await self.load(member_id)
        return None if member is None else member.name


SCHEMAS = (
    EventSchemaRegistry()
    .register(
        EventSchema(
            "member.opened",
            1,
            MemberOpened,
            lambda event: event.name.encode(),
            lambda payload: MemberOpened(payload.decode()),
        )
    )
    .freeze()
)


@dataclass(frozen=True, slots=True)
class OpenMember(Command[Member]):
    member_id: int
    name: str


@dataclass(frozen=True, slots=True)
class Noop(Command[object]):
    result: object


@dataclass(frozen=True, slots=True)
class Undecorated(Command[str]):
    pass


@dataclass(frozen=True, slots=True)
class TerminalFailure(Command[None]):
    pass


@dataclass(frozen=True, slots=True)
class TerminalCancellation(Command[None]):
    pass


@dataclass(frozen=True, slots=True)
class ReadMember(Query[str | None]):
    member_id: int


@dataclass(frozen=True, slots=True)
class InvalidRepositoryQuery(Query[None]):
    pass


@dataclass(frozen=True, slots=True)
class Ping(Event):
    pass


class TrackingUnitOfWork(EventSourcingUnitOfWork):
    def __init__(self, store, calls: list[str]) -> None:
        super().__init__(store)
        self.calls = calls

    async def __aenter__(self):
        self.calls.append("uow:enter")
        return await super().__aenter__()

    async def commit(self):
        self.calls.append("uow:commit")
        return await super().commit()

    async def rollback(self):
        self.calls.append("uow:rollback")
        return await super().rollback()

    async def __aexit__(self, error_type, error, traceback):
        self.calls.append("uow:exit")
        return await super().__aexit__(error_type, error, traceback)


class UowFactory:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.instances: list[TrackingUnitOfWork] = []

    async def __call__(self, store):
        unit_of_work = TrackingUnitOfWork(store, self.calls)
        self.instances.append(unit_of_work)
        return unit_of_work


class HandlerResource:
    pass


class FailingHandlerResource:
    pass


def handler_resource(calls: list[str]):
    @asynccontextmanager
    async def managed() -> AsyncIterator[HandlerResource]:
        calls.append("handler-resource:enter")
        try:
            yield HandlerResource()
        finally:
            calls.append("handler-resource:exit")

    return managed()


def failing_handler_resource(calls: list[str]):
    @asynccontextmanager
    async def managed() -> AsyncIterator[FailingHandlerResource]:
        calls.append("failing-resource:enter")
        try:
            yield FailingHandlerResource()
        finally:
            calls.append("failing-resource:exit")
            raise OSError("handler resource cleanup failed")

    return managed()


class AfterHandlerLeaseInterceptor:
    def __init__(
        self,
        members: Annotated[MemberRepo, aggregate_repository(MemberRepo)],
    ) -> None:
        self.members = members

    async def intercept(self, context: CqrsInvocationContext, next) -> object:
        del context
        result = await next()
        with pytest.raises(CommandTransactionUnavailableError):
            await self.members.load(1)
        return result


class FailingTerminalInterceptor:
    async def intercept(self, context: CqrsInvocationContext, next) -> object:
        def fail() -> None:
            raise ValueError("terminal callback failed")

        context.on_handler_exit(fail)
        return await next()


class CancellingTerminalInterceptor:
    def __init__(self) -> None:
        self.cancellation = asyncio.CancelledError("terminal callback cancelled")

    async def intercept(self, context: CqrsInvocationContext, next) -> object:
        def cancel() -> None:
            raise self.cancellation

        context.on_handler_exit(cancel)
        return await next()


@use_event_sourcing(key="lifecycle")
@use_cqrs_interceptors(AfterHandlerLeaseInterceptor)
@CommandHandler(OpenMember)
class OpenMemberHandler:
    def __init__(
        self,
        members: Annotated[MemberRepo, aggregate_repository(MemberRepo)],
        resource: HandlerResource,
    ) -> None:
        self.members = members
        self.resource = resource

    async def handle(self, command: OpenMember) -> Member:
        member = Member(command.member_id)
        member.open(command.name)
        self.members.save(member)
        return member


@use_event_sourcing(key="lifecycle")
@CommandHandler(Noop)
class NoopHandler:
    async def handle(self, command: Noop) -> object:
        return command.result


@CommandHandler(Undecorated)
class UndecoratedHandler:
    async def handle(self, command: Undecorated) -> str:
        del command
        return "plain"


@use_event_sourcing(key="lifecycle")
@use_cqrs_interceptors(FailingTerminalInterceptor)
@CommandHandler(TerminalFailure)
class TerminalFailureHandler:
    def __init__(self, resource: FailingHandlerResource) -> None:
        self.resource = resource

    async def handle(self, command: TerminalFailure) -> None:
        del command
        raise RuntimeError("terminal decision failed")


@use_event_sourcing(key="lifecycle")
@use_cqrs_interceptors(CancellingTerminalInterceptor)
@CommandHandler(TerminalCancellation)
class TerminalCancellationHandler:
    async def handle(self, command: TerminalCancellation) -> None:
        del command
        raise RuntimeError("cancelled terminal decision failed")


@QueryHandler(ReadMember)
class ReadMemberHandler:
    def __init__(
        self,
        store: Annotated[
            EventStore,
            Inject(get_event_store_token(key="lifecycle")),
        ],
    ) -> None:
        self.store = store

    async def handle(self, query: ReadMember) -> str | None:
        async with EventSourcingUnitOfWork(self.store) as unit_of_work:
            repository = MemberRepo(
                unit_of_work,
                category="member",
                aggregate_factory=Member,
                aggregate_type=Member,
                id_encoder=str,
                schemas=SCHEMAS,
            )
            return await repository.named(query.member_id)


@QueryHandler(InvalidRepositoryQuery)
class InvalidRepositoryQueryHandler:
    def __init__(
        self,
        members: Annotated[MemberRepo, aggregate_repository(MemberRepo)],
    ) -> None:
        self.members = members

    async def handle(self, query: InvalidRepositoryQuery) -> None:
        del query


class EventTracker:
    def __init__(self) -> None:
        self.opened = 0
        self.pings = 0


@EventsHandler(MemberOpened)
class OpenedHandler:
    def __init__(self, tracker: EventTracker) -> None:
        self.tracker = tracker

    async def handle(self, event: MemberOpened) -> None:
        del event
        self.tracker.opened += 1


@EventsHandler(Ping)
class PingHandler:
    def __init__(self, tracker: EventTracker) -> None:
        self.tracker = tracker

    async def handle(self, event: Ping) -> None:
        del event
        self.tracker.pings += 1


async def build_application(calls: list[str]):
    factory = UowFactory(calls)

    @module(
        providers=[ClassProvider(InMemoryEventStore)],
        exports=[InMemoryEventStore],
    )
    class Persistence:
        pass

    event_sourcing = CqrsEventSourcingModule.for_root(
        CqrsEventSourcingOptions(
            store=InMemoryEventStore,
            schemas=SCHEMAS,
            unit_of_work_factory=factory,
        ),
        imports=[Persistence],
        key="lifecycle",
    )
    repositories = CqrsEventSourcingModule.for_feature(
        [MemberRepo],
        root_key="lifecycle",
    )

    def create_resource():
        return handler_resource(calls)

    def create_failing_resource():
        return failing_handler_resource(calls)

    @module(
        imports=[repositories],
        providers=[
            FactoryProvider(
                HandlerResource,
                create_resource,
                scope=Scope.REQUEST,
            ),
            FactoryProvider(
                FailingHandlerResource,
                create_failing_resource,
                scope=Scope.REQUEST,
            ),
            ClassProvider(OpenMemberHandler, scope=Scope.REQUEST),
            ClassProvider(AfterHandlerLeaseInterceptor, scope=Scope.REQUEST),
            ClassProvider(NoopHandler, scope=Scope.REQUEST),
            ClassProvider(UndecoratedHandler),
            ClassProvider(FailingTerminalInterceptor, scope=Scope.REQUEST),
            ClassProvider(CancellingTerminalInterceptor, scope=Scope.REQUEST),
            ClassProvider(TerminalFailureHandler, scope=Scope.REQUEST),
            ClassProvider(TerminalCancellationHandler, scope=Scope.REQUEST),
            ClassProvider(ReadMemberHandler),
            ClassProvider(InvalidRepositoryQueryHandler, scope=Scope.REQUEST),
            ClassProvider(EventTracker),
            ClassProvider(OpenedHandler),
            ClassProvider(PingHandler),
        ],
        exports=[
            OpenMemberHandler,
            NoopHandler,
            UndecoratedHandler,
            TerminalFailureHandler,
            TerminalCancellationHandler,
            ReadMemberHandler,
            InvalidRepositoryQueryHandler,
            OpenedHandler,
            PingHandler,
        ],
    )
    class Handlers:
        pass

    cqrs = CqrsModule.for_root(imports=[Handlers], key="lifecycle")

    @module(imports=[event_sourcing, cqrs])
    class App:
        pass

    application = await TestingModule.create(App).compile()
    return application, factory, Handlers


@pytest.mark.asyncio
async def test_transaction_order_result_retention_reload_and_no_publication() -> None:
    calls: list[str] = []
    application, factory, handlers = await build_application(calls)
    commands = await application.resolve(CommandBus, module=(CqrsModule, "lifecycle"))
    queries = await application.resolve(QueryBus, module=(CqrsModule, "lifecycle"))
    events = await application.resolve(EventBus, module=(CqrsModule, "lifecycle"))
    tracker = await application.resolve(EventTracker, module=handlers)

    member = await commands.execute(OpenMember(1, "Mina"))
    assert isinstance(member, Member)
    assert member.version == 1
    assert await queries.execute(ReadMember(1)) == "Mina"
    assert calls == [
        "uow:enter",
        "handler-resource:enter",
        "uow:commit",
        "handler-resource:exit",
        "uow:exit",
    ]
    assert len(factory.instances) == 1
    assert tracker.opened == 0
    with pytest.raises(CommandTransactionUnavailableError):
        await queries.execute(InvalidRepositoryQuery())
    assert len(factory.instances) == 1
    await events.publish(Ping())
    await events.drain(timeout=1)
    assert tracker.pings == 1
    assert len(factory.instances) == 1
    await application.close()


@pytest.mark.asyncio
async def test_noop_commits_exact_result_and_plain_handlers_open_no_uow() -> None:
    calls: list[str] = []
    application, factory, _ = await build_application(calls)
    commands = await application.resolve(CommandBus, module=(CqrsModule, "lifecycle"))
    result = object()
    assert await commands.execute(Noop(result)) is result
    assert calls == ["uow:enter", "uow:commit", "uow:exit"]
    before = len(factory.instances)
    assert await commands.execute(Undecorated()) == "plain"
    assert len(factory.instances) == before
    await application.close()


@pytest.mark.asyncio
async def test_terminal_callback_failure_retains_non_commit_outcome() -> None:
    calls: list[str] = []
    application, _, _ = await build_application(calls)
    commands = await application.resolve(CommandBus, module=(CqrsModule, "lifecycle"))
    with pytest.raises(ConfirmedNonCommitFinalizationError) as captured:
        await commands.execute(TerminalFailure())
    assert isinstance(captured.value.primary_error, RuntimeError)
    assert str(captured.value.primary_error) == "terminal decision failed"
    assert [str(error) for error in captured.value.secondary_errors] == [
        "terminal callback failed",
        "handler resource cleanup failed",
    ]
    assert calls == [
        "uow:enter",
        "failing-resource:enter",
        "uow:rollback",
        "failing-resource:exit",
        "uow:exit",
    ]
    await application.close()


@pytest.mark.asyncio
async def test_terminal_callback_cancellation_preserves_control_flow() -> None:
    calls: list[str] = []
    application, _, _ = await build_application(calls)
    commands = await application.resolve(CommandBus, module=(CqrsModule, "lifecycle"))
    with pytest.raises(CommandCancellationError) as captured:
        await commands.execute(TerminalCancellation())
    assert isinstance(captured.value.outcome, ConfirmedNonCommit)
    assert str(captured.value.cancellation) == "terminal callback cancelled"
    assert any(
        str(error) == "cancelled terminal decision failed"
        for error in captured.value.secondary_errors
    )
    await application.close()


@pytest.mark.asyncio
async def test_explicit_query_transaction_binding_fails_before_uow_creation() -> None:
    calls: list[str] = []
    factory = UowFactory(calls)

    class Handler:
        async def handle(self, query: ReadMember) -> str | None:
            del query
            return None

    @module(providers=[ClassProvider(InMemoryEventStore)], exports=[InMemoryEventStore])
    class Persistence:
        pass

    event_sourcing = CqrsEventSourcingModule.for_root(
        CqrsEventSourcingOptions(
            store=InMemoryEventStore,
            schemas=SCHEMAS,
            unit_of_work_factory=factory,
        ),
        imports=[Persistence],
        key="invalid-query",
    )

    @module(
        providers=[ClassProvider(Handler)],
        exports=[Handler],
    )
    class Handlers:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Handlers],
        handlers=[
            bind_query_handler(
                ReadMember,
                Handler,
                interceptors=[event_sourcing_transaction(key="invalid-query")],
            )
        ],
        key="invalid-query",
    )

    @module(imports=[event_sourcing, cqrs])
    class App:
        pass

    with pytest.raises(CqrsConfigurationError, match="incompatible"):
        await TestingModule.create(App).compile()
    assert factory.instances == []


@pytest.mark.asyncio
async def test_handler_failure_rolls_back_before_uow_exit() -> None:
    calls: list[str] = []

    @dataclass(frozen=True, slots=True)
    class Fail(Command[None]):
        pass

    @use_event_sourcing(key="failure")
    @CommandHandler(Fail)
    class FailHandler:
        async def handle(self, command: Fail) -> None:
            del command
            raise RuntimeError("decision failed")

    factory = UowFactory(calls)

    @module(providers=[ClassProvider(InMemoryEventStore)], exports=[InMemoryEventStore])
    class Persistence:
        pass

    event_sourcing = CqrsEventSourcingModule.for_root(
        CqrsEventSourcingOptions(
            store=InMemoryEventStore,
            schemas=SCHEMAS,
            unit_of_work_factory=factory,
        ),
        imports=[Persistence],
        key="failure",
    )

    @module(
        providers=[ClassProvider(FailHandler, scope=Scope.REQUEST)],
        exports=[FailHandler],
    )
    class Handlers:
        pass

    cqrs = CqrsModule.for_root(imports=[Handlers], key="failure")

    @module(imports=[event_sourcing, cqrs])
    class App:
        pass

    application = await TestingModule.create(App).compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "failure"))
    assert isinstance(commands, CommandBus)
    with pytest.raises(RuntimeError, match="decision failed"):
        await commands.execute(Fail())
    assert calls == ["uow:enter", "uow:rollback", "uow:exit"]
    await application.close()


@pytest.mark.asyncio
async def test_repository_lease_rejects_post_body_and_child_task_use() -> None:
    calls: list[str] = []

    @dataclass(frozen=True, slots=True)
    class Escape(Command[MemberRepo]):
        pass

    @dataclass(frozen=True, slots=True)
    class ChildUse(Command[bool]):
        pass

    @use_event_sourcing(key="lease")
    @CommandHandler(Escape)
    class EscapeHandler:
        def __init__(
            self,
            members: Annotated[MemberRepo, aggregate_repository(MemberRepo)],
        ) -> None:
            self.members = members

        async def handle(self, command: Escape) -> MemberRepo:
            del command
            return self.members

    @use_event_sourcing(key="lease")
    @CommandHandler(ChildUse)
    class ChildHandler:
        def __init__(
            self,
            members: Annotated[MemberRepo, aggregate_repository(MemberRepo)],
        ) -> None:
            self.members = members

        async def handle(self, command: ChildUse) -> bool:
            del command

            async def use() -> None:
                await self.members.load(1)

            with pytest.raises(CommandTransactionUnavailableError):
                await asyncio.create_task(use())
            return True

    factory = UowFactory(calls)

    @module(providers=[ClassProvider(InMemoryEventStore)], exports=[InMemoryEventStore])
    class Persistence:
        pass

    event_sourcing = CqrsEventSourcingModule.for_root(
        CqrsEventSourcingOptions(
            store=InMemoryEventStore,
            schemas=SCHEMAS,
            unit_of_work_factory=factory,
        ),
        imports=[Persistence],
        key="lease",
    )
    repositories = CqrsEventSourcingModule.for_feature(
        [MemberRepo],
        root_key="lease",
        key="lease-feature",
    )

    @module(
        imports=[repositories],
        providers=[
            ClassProvider(EscapeHandler, scope=Scope.REQUEST),
            ClassProvider(ChildHandler, scope=Scope.REQUEST),
        ],
        exports=[EscapeHandler, ChildHandler],
    )
    class Handlers:
        pass

    cqrs = CqrsModule.for_root(imports=[Handlers], key="lease")

    @module(imports=[event_sourcing, cqrs])
    class App:
        pass

    application = await TestingModule.create(App).compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "lease"))
    assert isinstance(commands, CommandBus)
    escaped = await commands.execute(Escape())
    with pytest.raises(CommandTransactionUnavailableError):
        await escaped.load(1)
    assert await commands.execute(ChildUse()) is True
    await application.close()


@pytest.mark.asyncio
async def test_cleanup_after_commit_is_confirmed_finalization_failure() -> None:
    @dataclass(frozen=True, slots=True)
    class Finish(Command[int]):
        pass

    class FailingResource:
        pass

    def failing_resource():
        @asynccontextmanager
        async def managed() -> AsyncIterator[FailingResource]:
            yield FailingResource()
            raise RuntimeError("resource cleanup failed")

        return managed()

    @use_event_sourcing(key="cleanup")
    @CommandHandler(Finish)
    class FinishHandler:
        def __init__(self, resource: FailingResource) -> None:
            self.resource = resource

        async def handle(self, command: Finish) -> int:
            del command
            return 17

    @module(providers=[ClassProvider(InMemoryEventStore)], exports=[InMemoryEventStore])
    class Persistence:
        pass

    event_sourcing = CqrsEventSourcingModule.for_root(
        CqrsEventSourcingOptions(store=InMemoryEventStore, schemas=SCHEMAS),
        imports=[Persistence],
        key="cleanup",
    )

    @module(
        providers=[
            FactoryProvider(FailingResource, failing_resource, scope=Scope.REQUEST),
            ClassProvider(FinishHandler, scope=Scope.REQUEST),
        ],
        exports=[FinishHandler],
    )
    class Handlers:
        pass

    cqrs = CqrsModule.for_root(imports=[Handlers], key="cleanup")

    @module(imports=[event_sourcing, cqrs])
    class App:
        pass

    application = await TestingModule.create(App).compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "cleanup"))
    assert isinstance(commands, CommandBus)
    with pytest.raises(ConfirmedCommandFinalizationError) as captured:
        await commands.execute(Finish())
    assert captured.value.handler_result == 17
    assert str(captured.value.primary_error) == "resource cleanup failed"
    assert captured.value.commit_result.events == ()
    await application.close()
