"""Request-scoped command transaction coordination."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType
from typing import cast

from tori_py import ScopeCancellationError, ScopeFinalizationError
from tori_py_cqrs import (
    CqrsHandlerExitCancellationError,
    CqrsHandlerExitError,
    CqrsInvocationContext,
    CqrsNext,
    CqrsScopeCompletion,
)
from tori_py_cqrs_core import HandlerKind
from tori_py_cqrs_event_sourcing_core import (
    ConfirmedCommit,
    ConfirmedCommitCleanupError,
    ConfirmedNonCommit,
    EventSourcingUnitOfWork,
    EventStore,
    UnitOfWorkLifecycleError,
    UnitOfWorkOutcome,
)

from tori_py_cqrs_event_sourcing.errors import (
    CommandCancellationError,
    CommandFinalizationPhase,
    CommandSynchronizationStateError,
    CommandTransactionUnavailableError,
    ConfirmedCommandFinalizationError,
    ConfirmedNonCommitFinalizationError,
    CqrsEventSourcingConfigurationError,
    IndeterminateCommandFinalizationError,
)
from tori_py_cqrs_event_sourcing.options import UnitOfWorkFactory
from tori_py_cqrs_event_sourcing.synchronization import (
    CommandSynchronization,
    CommitCallback,
    Finalizer,
    IndeterminateCallback,
)


class _TransactionAccessor:
    __slots__ = ("_active", "_owner", "_unit_of_work")

    def __init__(self) -> None:
        self._active = False
        self._owner: asyncio.Task[object] | None = None
        self._unit_of_work: EventSourcingUnitOfWork | None = None

    def activate(self, unit_of_work: EventSourcingUnitOfWork) -> None:
        if self._unit_of_work is not None:
            raise CommandTransactionUnavailableError(
                "command transaction cannot be activated"
            )
        self._unit_of_work = unit_of_work
        self._active = True

    def bind_body_owner(self) -> None:
        owner = asyncio.current_task()
        if owner is None or self._owner is not None or not self._active:
            raise CommandTransactionUnavailableError(
                "command transaction body cannot be bound"
            )
        self._owner = cast(asyncio.Task[object], owner)

    def close_body(self) -> None:
        self._active = False

    def deactivate(self) -> None:
        self._active = False
        self._owner = None

    def require(self) -> EventSourcingUnitOfWork:
        if (
            not self._active
            or self._unit_of_work is None
            or asyncio.current_task() is not self._owner
        ):
            raise CommandTransactionUnavailableError(
                "repository operation requires its owning command body"
            )
        return self._unit_of_work

    def current(self) -> EventSourcingUnitOfWork:
        if not self._active or self._unit_of_work is None:
            raise CommandTransactionUnavailableError(
                "repository resolution requires an active decorated command"
            )
        return self._unit_of_work


class _CommandSynchronizationState(CommandSynchronization):
    __slots__ = (
        "_after_commit",
        "_after_indeterminate",
        "_after_non_commit",
        "_callback_errors",
        "_open",
        "_owner",
    )

    def __init__(self) -> None:
        self._owner: asyncio.Task[object] | None = None
        self._open = False
        self._after_commit: list[CommitCallback] = []
        self._after_non_commit: list[Finalizer] = []
        self._after_indeterminate: list[IndeterminateCallback] = []
        self._callback_errors: list[BaseException] = []

    @property
    def callback_errors(self) -> tuple[BaseException, ...]:
        return tuple(self._callback_errors)

    def activate(self) -> None:
        if self._owner is not None or self._open:
            raise CommandSynchronizationStateError(
                "command synchronization cannot be activated"
            )

    def bind_body_owner(self) -> None:
        owner = asyncio.current_task()
        if owner is None or self._owner is not None:
            raise CommandSynchronizationStateError(
                "command synchronization body cannot be bound"
            )
        self._owner = cast(asyncio.Task[object], owner)
        self._open = True

    def close_registration(self) -> None:
        self._open = False

    def after_commit(self, callback: CommitCallback) -> None:
        self._register(callback, self._after_commit)

    def after_confirmed_non_commit(self, callback: Finalizer) -> None:
        self._register(callback, self._after_non_commit)

    def after_indeterminate(self, callback: IndeterminateCallback) -> None:
        self._register(callback, self._after_indeterminate)

    def _register[CallbackT](
        self,
        callback: CallbackT,
        target: list[CallbackT],
    ) -> None:
        if (
            not self._open
            or asyncio.current_task() is not self._owner
            or not callable(callback)
        ):
            raise CommandSynchronizationStateError(
                "synchronization callbacks require the owning command body"
            )
        target.append(callback)

    async def run(self, outcome: UnitOfWorkOutcome) -> None:
        if isinstance(outcome, ConfirmedCommit):
            callbacks: tuple[Callable[..., object], ...] = tuple(self._after_commit)
            arguments: tuple[object, ...] = (outcome.result,)
        elif isinstance(outcome, ConfirmedNonCommit):
            callbacks = tuple(reversed(self._after_non_commit))
            arguments = ()
        else:
            callbacks = tuple(self._after_indeterminate)
            arguments = (outcome.cause,)
        for callback in callbacks:
            try:
                selected = cast(Callable[..., object], callback)
                result = selected(*arguments)
                if inspect.isawaitable(result):
                    await result
            except Exception as error:
                self._callback_errors.append(error)
            except BaseException:
                raise


@dataclass(slots=True)
class _TransactionRecord:
    unit_of_work: EventSourcingUnitOfWork | None = None
    outcome: UnitOfWorkOutcome | None = None
    handler_result: object | None = None
    result_available: bool = False
    primary_error: BaseException | None = None
    primary_phase: CommandFinalizationPhase = CommandFinalizationPhase.COMMIT
    control_phase: CommandFinalizationPhase | None = None
    operation_errors: list[tuple[CommandFinalizationPhase, BaseException]] = field(
        default_factory=list
    )
    uow_cleanup_errors: list[BaseException] = field(default_factory=list)


class _CommandTransactionCoordinator:
    __slots__ = (
        "_accessor",
        "_factory",
        "_record",
        "_store",
        "_synchronization",
    )

    def __init__(
        self,
        store: EventStore,
        synchronization: _CommandSynchronizationState,
        accessor: _TransactionAccessor,
        factory: UnitOfWorkFactory,
    ) -> None:
        self._store = store
        self._synchronization = synchronization
        self._accessor = accessor
        self._factory = factory
        self._record = _TransactionRecord()

    @property
    def unit_of_work(self) -> EventSourcingUnitOfWork:
        unit_of_work = self._record.unit_of_work
        if unit_of_work is None:
            raise CommandTransactionUnavailableError(
                "command transaction has not entered"
            )
        return unit_of_work

    async def __aenter__(self) -> _CommandTransactionCoordinator:
        created = self._factory(self._store)
        if inspect.isawaitable(created):
            created = await created
        if not isinstance(created, EventSourcingUnitOfWork):
            raise CqrsEventSourcingConfigurationError(
                "unit_of_work_factory must return an unentered EventSourcingUnitOfWork"
            )
        entered = await created.__aenter__()
        if entered is not created:
            await created.__aexit__(None, None, None)
            raise CqrsEventSourcingConfigurationError(
                "Unit of Work context must return itself"
            )
        self._record.unit_of_work = created
        self._accessor.activate(created)
        self._synchronization.activate()
        return self

    async def __aexit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._accessor.close_body()
        self._synchronization.close_registration()
        unit_of_work = self._record.unit_of_work
        if unit_of_work is None:
            return
        if self._read_outcome() is None:
            try:
                await unit_of_work.rollback()
            except BaseException as rollback_error:
                self._record.operation_errors.append(
                    (CommandFinalizationPhase.HANDLER_ROLLBACK, rollback_error)
                )
        try:
            await unit_of_work.__aexit__(error_type, error, traceback)
        except ConfirmedCommitCleanupError as cleanup_error:
            self._record.uow_cleanup_errors.append(cleanup_error.cleanup_error)
        except Exception as cleanup_error:
            self._record.uow_cleanup_errors.append(cleanup_error)
        finally:
            self._accessor.deactivate()
            self._read_outcome()

    def register_completion(self, context: CqrsInvocationContext, key: str) -> None:
        context.completion.register(key, self._map_completion)

    def close_body(self) -> None:
        self._accessor.close_body()
        self._synchronization.close_registration()

    def begin_body(self) -> None:
        self._accessor.bind_body_owner()
        self._synchronization.bind_body_owner()

    def set_primary(
        self,
        error: BaseException,
        phase: CommandFinalizationPhase,
    ) -> None:
        self._record.primary_error = error
        self._record.primary_phase = phase

    def set_control_phase(self, phase: CommandFinalizationPhase) -> None:
        self._record.control_phase = phase

    def retain_result(self, result: object) -> None:
        self._record.handler_result = result
        self._record.result_available = True

    async def rollback(self) -> None:
        try:
            await self.unit_of_work.rollback()
        except BaseException as error:
            self._record.operation_errors.append(
                (CommandFinalizationPhase.HANDLER_ROLLBACK, error)
            )
        self._read_outcome()

    async def commit(self) -> None:
        try:
            await self.unit_of_work.commit()
        finally:
            self._read_outcome()

    async def synchronize(self) -> None:
        outcome = self._read_outcome()
        if outcome is None:
            raise CommandTransactionUnavailableError(
                "transaction outcome is unavailable for synchronization"
            )
        await self._synchronization.run(outcome)

    def _read_outcome(self) -> UnitOfWorkOutcome | None:
        unit_of_work = self._record.unit_of_work
        if unit_of_work is None:
            return None
        try:
            outcome = unit_of_work.outcome
        except UnitOfWorkLifecycleError:
            return None
        self._record.outcome = outcome
        return outcome

    def _map_completion(
        self,
        completion: CqrsScopeCompletion,
        current: BaseException | None,
    ) -> BaseException | None:
        outcome = self._record.outcome
        if outcome is None:
            return current

        body_error = completion.body_error
        scope_errors = (
            ()
            if completion.scope_error is None
            else completion.scope_error.cleanup_errors
        )
        handler_exit_errors: tuple[BaseException, ...] = ()
        if isinstance(current, CqrsHandlerExitCancellationError):
            if body_error is None:
                body_error = current.cancellation
                handler_exit_errors = current.secondary_errors
            else:
                handler_exit_errors = (
                    current.cancellation,
                    *current.secondary_errors,
                )
        elif isinstance(current, CqrsHandlerExitError):
            if body_error is None:
                body_error = current.body_error
            handler_exit_errors = current.callback_errors
        elif body_error is None and isinstance(
            current, ScopeFinalizationError | ScopeCancellationError
        ):
            body_error = current.body_error
        elif body_error is None and current is not None:
            body_error = current

        entries: list[tuple[CommandFinalizationPhase, BaseException]] = []
        primary = self._record.primary_error or body_error
        if primary is not None:
            entries.append((self._record.primary_phase, primary))
        entries.extend(self._record.operation_errors)
        entries.extend(
            (CommandFinalizationPhase.HANDLER_FINALIZATION, error)
            for error in handler_exit_errors
        )
        entries.extend(
            (CommandFinalizationPhase.SYNCHRONIZATION, error)
            for error in self._synchronization.callback_errors
        )
        entries.extend(
            (CommandFinalizationPhase.SCOPE_CLEANUP, error) for error in scope_errors
        )
        entries.extend(
            (CommandFinalizationPhase.UOW_CLEANUP, error)
            for error in self._record.uow_cleanup_errors
        )
        if body_error is not None and all(
            error is not body_error for _, error in entries
        ):
            entries.insert(0, (CommandFinalizationPhase.SCOPE_CLEANUP, body_error))
        entries = _identity_unique(entries)

        control = next(
            (
                error
                for _, error in entries
                if isinstance(error, (KeyboardInterrupt, SystemExit))
            ),
            None,
        )
        if control is not None:
            for _, secondary in entries:
                if secondary is not control:
                    control.add_note(
                        "command finalization also failed: "
                        f"{type(secondary).__name__}: {secondary}"
                    )
            return control

        cancellation = next(
            (
                error
                for _, error in entries
                if isinstance(error, asyncio.CancelledError)
            ),
            None,
        )
        if isinstance(cancellation, asyncio.CancelledError):
            phase = self._record.control_phase or next(
                phase for phase, error in entries if error is cancellation
            )
            return CommandCancellationError(
                outcome=outcome,
                cancellation=cancellation,
                phase=phase,
                secondary_errors=tuple(
                    error for _, error in entries if error is not cancellation
                ),
            )

        if not entries:
            return current
        phase, primary_error = entries[0]
        secondary = tuple(error for _, error in entries[1:])
        has_finalization_error = bool(
            self._record.operation_errors
            or handler_exit_errors
            or self._synchronization.callback_errors
            or scope_errors
            or self._record.uow_cleanup_errors
        )
        if isinstance(outcome, ConfirmedCommit):
            return ConfirmedCommandFinalizationError(
                commit_result=outcome.result,
                handler_result=self._record.handler_result,
                phase=phase,
                primary_error=primary_error,
                secondary_errors=secondary,
            )
        if not has_finalization_error and current is not None:
            return current
        if isinstance(outcome, ConfirmedNonCommit):
            return ConfirmedNonCommitFinalizationError(
                outcome=outcome,
                phase=phase,
                primary_error=primary_error,
                secondary_errors=secondary,
            )
        return IndeterminateCommandFinalizationError(
            outcome=outcome,
            phase=phase,
            primary_error=primary_error,
            secondary_errors=secondary,
        )


class _TransactionInterceptor:
    __slots__ = ("_coordinator", "_completion_key")

    def __init__(
        self,
        coordinator: _CommandTransactionCoordinator,
        completion_key: str,
    ) -> None:
        self._coordinator = coordinator
        self._completion_key = completion_key

    async def intercept(
        self,
        context: CqrsInvocationContext,
        next: CqrsNext,
    ) -> object:
        if context.handler_kind is not HandlerKind.COMMAND:
            raise CqrsEventSourcingConfigurationError(
                "event sourcing can only intercept command handlers"
            )
        self._coordinator.register_completion(context, self._completion_key)
        self._coordinator.begin_body()
        context.on_handler_exit(self._coordinator.close_body)
        try:
            result = await next()
        except BaseException as handler_error:
            self._coordinator.close_body()
            self._coordinator.set_primary(
                handler_error,
                CommandFinalizationPhase.HANDLER_ROLLBACK,
            )
            await self._coordinator.rollback()
            try:
                await self._coordinator.synchronize()
            except BaseException:
                self._coordinator.set_control_phase(
                    CommandFinalizationPhase.SYNCHRONIZATION
                )
                raise
            raise

        self._coordinator.close_body()
        self._coordinator.retain_result(result)
        try:
            await self._coordinator.commit()
        except BaseException as commit_error:
            self._coordinator.set_primary(
                commit_error,
                CommandFinalizationPhase.COMMIT,
            )
            try:
                await self._coordinator.synchronize()
            except BaseException:
                self._coordinator.set_control_phase(
                    CommandFinalizationPhase.SYNCHRONIZATION
                )
                raise
            raise
        try:
            await self._coordinator.synchronize()
        except BaseException:
            self._coordinator.set_control_phase(
                CommandFinalizationPhase.SYNCHRONIZATION
            )
            raise
        return result


def _identity_unique(
    entries: list[tuple[CommandFinalizationPhase, BaseException]],
) -> list[tuple[CommandFinalizationPhase, BaseException]]:
    seen: set[int] = set()
    result: list[tuple[CommandFinalizationPhase, BaseException]] = []
    for entry in entries:
        identity = id(entry[1])
        if identity not in seen:
            seen.add(identity)
            result.append(entry)
    return result


__all__: list[str] = []
