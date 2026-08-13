import asyncio
from dataclasses import dataclass
from typing import Annotated

import pytest
from tori_py import ClassProvider, Inject, Scope, module
from tori_py.testing import TestingModule
from tori_py_cqrs import CqrsModule
from tori_py_cqrs_core import Command, CommandBus, CommandHandler
from tori_py_cqrs_event_sourcing import (
    CommandCancellationError,
    CommandFinalizationPhase,
    CommandSynchronization,
    CommandSynchronizationStateError,
    ConfirmedCommandFinalizationError,
    ConfirmedNonCommitFinalizationError,
    CqrsEventSourcingModule,
    CqrsEventSourcingOptions,
    get_command_synchronization_token,
    use_event_sourcing,
)
from tori_py_cqrs_event_sourcing_core import (
    ConfirmedNonCommit,
    EventSchemaRegistry,
    InMemoryEventStore,
)


@dataclass(frozen=True, slots=True)
class Succeed(Command[str]):
    fail_callback: bool = False


@dataclass(frozen=True, slots=True)
class Fail(Command[None]):
    fail_compensation: bool = False


@dataclass(frozen=True, slots=True)
class Cancel(Command[None]):
    pass


async def build_application(calls: list[str], escaped: list[CommandSynchronization]):
    @use_event_sourcing(key="sync")
    @CommandHandler(Succeed)
    class SucceedHandler:
        def __init__(
            self,
            synchronization: Annotated[
                CommandSynchronization,
                Inject(get_command_synchronization_token(key="sync")),
            ],
        ) -> None:
            self.synchronization = synchronization

        async def handle(self, command: Succeed) -> str:
            escaped.append(self.synchronization)

            async def first(result) -> None:
                assert result.events == ()
                calls.append("commit:first")
                if command.fail_callback:
                    raise RuntimeError("commit callback failed")

            self.synchronization.after_commit(first)
            self.synchronization.after_commit(
                lambda result: calls.append(f"commit:second:{len(result.events)}")
            )
            self.synchronization.after_confirmed_non_commit(
                lambda: calls.append("wrong:non-commit")
            )
            self.synchronization.after_indeterminate(
                lambda error: calls.append(f"wrong:indeterminate:{error}")
            )
            return "result"

    @use_event_sourcing(key="sync")
    @CommandHandler(Fail)
    class FailHandler:
        def __init__(
            self,
            synchronization: Annotated[
                CommandSynchronization,
                Inject(get_command_synchronization_token(key="sync")),
            ],
        ) -> None:
            self.synchronization = synchronization

        async def handle(self, command: Fail) -> None:
            def first() -> None:
                calls.append("compensate:first")
                if command.fail_compensation:
                    raise RuntimeError("compensation failed")

            self.synchronization.after_confirmed_non_commit(first)
            self.synchronization.after_confirmed_non_commit(
                lambda: calls.append("compensate:second")
            )
            raise ValueError("handler failed")

    @use_event_sourcing(key="sync")
    @CommandHandler(Cancel)
    class CancelHandler:
        def __init__(
            self,
            synchronization: Annotated[
                CommandSynchronization,
                Inject(get_command_synchronization_token(key="sync")),
            ],
        ) -> None:
            self.synchronization = synchronization

        async def handle(self, command: Cancel) -> None:
            del command
            self.synchronization.after_confirmed_non_commit(
                lambda: calls.append("compensate:cancel")
            )
            raise asyncio.CancelledError("handler cancelled")

    @module(providers=[ClassProvider(InMemoryEventStore)], exports=[InMemoryEventStore])
    class Persistence:
        pass

    event_sourcing = CqrsEventSourcingModule.for_root(
        CqrsEventSourcingOptions(
            store=InMemoryEventStore,
            schemas=EventSchemaRegistry().freeze(),
        ),
        imports=[Persistence],
        key="sync",
    )

    @module(
        providers=[
            ClassProvider(SucceedHandler, scope=Scope.REQUEST),
            ClassProvider(FailHandler, scope=Scope.REQUEST),
            ClassProvider(CancelHandler, scope=Scope.REQUEST),
        ],
        exports=[SucceedHandler, FailHandler, CancelHandler],
    )
    class Handlers:
        pass

    cqrs = CqrsModule.for_root(imports=[Handlers], key="sync")

    @module(imports=[event_sourcing, cqrs])
    class App:
        pass

    return await TestingModule.create(App).compile()


@pytest.mark.asyncio
async def test_commit_callbacks_are_fifo_async_and_outcome_specific() -> None:
    calls: list[str] = []
    escaped: list[CommandSynchronization] = []
    application = await build_application(calls, escaped)
    commands = await application.resolve(CommandBus, module=(CqrsModule, "sync"))
    assert isinstance(commands, CommandBus)

    assert await commands.execute(Succeed()) == "result"
    assert calls == ["commit:first", "commit:second:0"]
    with pytest.raises(CommandSynchronizationStateError):
        escaped[0].after_commit(lambda result: None)
    await application.close()


@pytest.mark.asyncio
async def test_commit_callback_failures_attempt_remaining_and_preserve_commit() -> None:
    calls: list[str] = []
    application = await build_application(calls, [])
    commands = await application.resolve(CommandBus, module=(CqrsModule, "sync"))
    assert isinstance(commands, CommandBus)

    with pytest.raises(ConfirmedCommandFinalizationError) as captured:
        await commands.execute(Succeed(fail_callback=True))
    assert calls == ["commit:first", "commit:second:0"]
    assert captured.value.handler_result == "result"
    assert captured.value.phase is CommandFinalizationPhase.SYNCHRONIZATION
    assert str(captured.value.primary_error) == "commit callback failed"
    await application.close()


@pytest.mark.asyncio
async def test_compensations_are_lifo_and_failures_preserve_non_commit() -> None:
    calls: list[str] = []
    application = await build_application(calls, [])
    commands = await application.resolve(CommandBus, module=(CqrsModule, "sync"))
    assert isinstance(commands, CommandBus)

    with pytest.raises(ConfirmedNonCommitFinalizationError) as captured:
        await commands.execute(Fail(fail_compensation=True))
    assert calls == ["compensate:second", "compensate:first"]
    assert isinstance(captured.value.outcome, ConfirmedNonCommit)
    assert isinstance(captured.value.primary_error, ValueError)
    assert len(captured.value.secondary_errors) == 1
    assert str(captured.value.secondary_errors[0]) == "compensation failed"
    await application.close()


@pytest.mark.asyncio
async def test_handler_cancellation_remains_cancellation_with_typed_outcome() -> None:
    calls: list[str] = []
    application = await build_application(calls, [])
    commands = await application.resolve(CommandBus, module=(CqrsModule, "sync"))
    assert isinstance(commands, CommandBus)

    with pytest.raises(CommandCancellationError) as captured:
        await commands.execute(Cancel())
    assert isinstance(captured.value, asyncio.CancelledError)
    assert isinstance(captured.value.outcome, ConfirmedNonCommit)
    assert isinstance(captured.value.cancellation, asyncio.CancelledError)
    assert calls == ["compensate:cancel"]
    await application.close()
