"""Event-sourced repositories and explicit Unit of Work ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Any

from cqrs_event_sourcing.aggregate import AggregateRoot
from cqrs_event_sourcing.codec import EventSchemaRegistry
from cqrs_event_sourcing.errors import (
    AggregateNotFoundError,
    AggregateTypeMismatchError,
    CommitResultMismatchError,
    ConfirmedCommitCleanupError,
    ConfirmedCommitError,
    DuplicateAggregateSaveError,
    DuplicateEventIdError,
    DuplicateStreamAggregateError,
    IndeterminateCommitError,
    OptimisticConcurrencyError,
    RepositoryError,
    ResourceLimitError,
    SchemaRegistryNotFrozenError,
    UnitOfWorkLifecycleError,
)
from cqrs_event_sourcing.events import (
    AppendEvent,
    CommitResult,
    PendingEvent,
    StreamId,
)
from cqrs_event_sourcing.outcomes import (
    ConfirmedCommit,
    ConfirmedNonCommit,
    IndeterminateCommit,
    UnitOfWorkOutcome,
)
from cqrs_event_sourcing.protocols import EventStore, EventStoreTransaction


class _UnitOfWorkState(StrEnum):
    NEW = "new"
    ENTERING = "entering"
    ACTIVE = "active"
    COMMITTING = "committing"
    ROLLING_BACK = "rolling_back"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAULTED = "faulted"


@dataclass(frozen=True, slots=True)
class _CommitPlan:
    aggregate: AggregateRoot[Any]
    stream_id: StreamId
    expected_version: int
    pending: tuple[PendingEvent, ...]
    append_events: tuple[AppendEvent, ...]

    @property
    def final_version(self) -> int:
        return self.expected_version + len(self.pending)


class EventSourcingUnitOfWork:
    """Own one EventStore transaction and every aggregate enlisted in it."""

    def __init__(self, store: EventStore) -> None:
        if not isinstance(store, EventStore):
            raise TypeError("store must implement EventStore")
        self._store = store
        self._state = _UnitOfWorkState.NEW
        self._context: AbstractAsyncContextManager[EventStoreTransaction] | None = None
        self._transaction: EventStoreTransaction | None = None
        self._plans: list[_CommitPlan] = []
        self._aggregates: set[int] = set()
        self._streams: set[StreamId] = set()
        self._commit_result: CommitResult | None = None
        self._outcome: UnitOfWorkOutcome | None = None

    @property
    def outcome(self) -> UnitOfWorkOutcome:
        """Return the final persistence outcome."""

        if self._outcome is None:
            raise UnitOfWorkLifecycleError(
                f"outcome is unavailable in {self._state} state"
            )
        return self._outcome

    @property
    def transaction(self) -> EventStoreTransaction:
        """Return the active EventStore transaction."""

        self._require_active("access transaction")
        assert self._transaction is not None
        return self._transaction

    async def __aenter__(self) -> EventSourcingUnitOfWork:
        if self._state is not _UnitOfWorkState.NEW:
            raise UnitOfWorkLifecycleError(
                f"cannot enter Unit of Work in {self._state} state"
            )
        self._state = _UnitOfWorkState.ENTERING
        try:
            context = self._store.transaction()
            transaction = await context.__aenter__()
        except BaseException as error:
            self._state = _UnitOfWorkState.ROLLED_BACK
            self._outcome = ConfirmedNonCommit(error)
            raise
        self._context = context
        self._transaction = transaction
        self._state = _UnitOfWorkState.ACTIVE
        return self

    async def __aexit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        context = self._context
        if context is None:
            return
        if self._state in {
            _UnitOfWorkState.COMMITTING,
            _UnitOfWorkState.ROLLING_BACK,
        }:
            raise UnitOfWorkLifecycleError(
                f"cannot exit Unit of Work in {self._state} state"
            )
        if self._state is _UnitOfWorkState.ACTIVE:
            try:
                await self._rollback(self.transaction, cause=error)
            except BaseException as rollback_error:
                self._fault_all()
                self._state = _UnitOfWorkState.FAULTED
                try:
                    await context.__aexit__(error_type, error, traceback)
                except BaseException as cleanup_error:
                    rollback_error.add_note(
                        f"transaction context cleanup also failed: {cleanup_error!r}"
                    )
                raise
        try:
            await context.__aexit__(error_type, error, traceback)
        except BaseException as cleanup_error:
            if (
                self._state is _UnitOfWorkState.COMMITTED
                and self._commit_result is not None
            ):
                raise ConfirmedCommitCleanupError(
                    result=self._commit_result,
                    cleanup_error=cleanup_error,
                ) from cleanup_error
            raise

    def validate_stage(
        self,
        aggregate: AggregateRoot[Any],
        *,
        stream_id: StreamId,
    ) -> None:
        """Reject aggregate/UoW lifecycle conflicts before event serialization."""

        self._require_active("stage aggregate")
        if id(aggregate) in self._aggregates:
            raise DuplicateAggregateSaveError(
                "aggregate is already saved in this Unit of Work"
            )
        if stream_id in self._streams:
            raise DuplicateStreamAggregateError(
                f"stream {stream_id!r} already has an aggregate in this Unit of Work"
            )
        AggregateRoot._validate_staging(aggregate, stream_id=stream_id)

    def stage(
        self,
        aggregate: AggregateRoot[Any],
        *,
        stream_id: StreamId,
        pending: tuple[PendingEvent, ...],
        append_events: tuple[AppendEvent, ...],
    ) -> None:
        """Exclusively enlist one aggregate and stage its only append batch."""

        self.validate_stage(aggregate, stream_id=stream_id)
        aggregate_identity = id(aggregate)
        AggregateRoot._enlist(
            aggregate,
            self,
            stream_id=stream_id,
            events=pending,
        )
        try:
            self.transaction.append(
                stream_id,
                expected_version=aggregate.version,
                events=append_events,
            )
        except BaseException:
            AggregateRoot._release(aggregate, self)
            raise
        self._plans.append(
            _CommitPlan(
                aggregate=aggregate,
                stream_id=stream_id,
                expected_version=aggregate.version,
                pending=pending,
                append_events=append_events,
            )
        )
        self._aggregates.add(aggregate_identity)
        self._streams.add(stream_id)

    async def commit(self) -> CommitResult:
        """Commit all streams and then advance every aggregate atomically."""

        transaction = self.transaction
        self._state = _UnitOfWorkState.COMMITTING
        prepared: list[tuple[_CommitPlan, object]] = []
        try:
            for plan in self._plans:
                prepared.append(
                    (
                        plan,
                        AggregateRoot._prepare_commit(
                            plan.aggregate,
                            self,
                            events=plan.pending,
                            version=plan.final_version,
                        ),
                    )
                )
        except BaseException as error:
            await self._rollback_and_fault(transaction, cause=error)
            raise

        try:
            result = await transaction.commit()
        except (OptimisticConcurrencyError, DuplicateEventIdError) as error:
            self._fault_all()
            self._state = _UnitOfWorkState.ROLLED_BACK
            self._outcome = ConfirmedNonCommit(error)
            raise
        except IndeterminateCommitError as error:
            self._fault_all()
            self._state = _UnitOfWorkState.FAULTED
            self._outcome = IndeterminateCommit(error)
            raise
        except asyncio.CancelledError as error:
            self._release_all()
            self._state = _UnitOfWorkState.ROLLED_BACK
            self._outcome = ConfirmedNonCommit(error)
            raise
        except ConfirmedCommitError as error:
            self._release_all()
            self._state = _UnitOfWorkState.ROLLED_BACK
            self._outcome = ConfirmedNonCommit(error)
            raise
        except BaseException as error:
            self._fault_all()
            self._state = _UnitOfWorkState.FAULTED
            self._outcome = IndeterminateCommit(error)
            raise

        try:
            self._validate_result(result)
        except BaseException as error:
            self._fault_all()
            self._state = _UnitOfWorkState.FAULTED
            self._outcome = IndeterminateCommit(error)
            raise
        self._commit_result = result
        self._outcome = ConfirmedCommit(result)
        for plan, transition in prepared:
            AggregateRoot._mark_committed(plan.aggregate, transition)
        self._state = _UnitOfWorkState.COMMITTED
        return result

    async def rollback(self) -> None:
        """Roll back staged storage work and release reusable aggregates."""

        transaction = self.transaction
        await self._rollback(transaction, cause=None)

    async def _rollback(
        self,
        transaction: EventStoreTransaction,
        *,
        cause: BaseException | None,
    ) -> None:
        self._state = _UnitOfWorkState.ROLLING_BACK
        try:
            await transaction.rollback()
        except BaseException as error:
            self._fault_all()
            self._state = _UnitOfWorkState.FAULTED
            self._outcome = ConfirmedNonCommit(cause if cause is not None else error)
            raise
        self._release_all()
        self._state = _UnitOfWorkState.ROLLED_BACK
        self._outcome = ConfirmedNonCommit(cause)

    async def _rollback_and_fault(
        self,
        transaction: EventStoreTransaction,
        *,
        cause: BaseException,
    ) -> None:
        try:
            await transaction.rollback()
        finally:
            self._fault_all()
            self._state = _UnitOfWorkState.FAULTED
            self._outcome = ConfirmedNonCommit(cause)

    def _validate_result(self, result: object) -> None:
        if not isinstance(result, CommitResult):
            raise CommitResultMismatchError("commit must return CommitResult")
        expected = [
            (plan.stream_id, plan.expected_version + offset, event)
            for plan in self._plans
            for offset, event in enumerate(plan.append_events, start=1)
        ]
        if len(result.events) != len(expected):
            raise CommitResultMismatchError(
                "commit result event count does not match staged events"
            )
        for stored, (stream_id, stream_version, event) in zip(
            result.events,
            expected,
            strict=True,
        ):
            if (
                stored.stream_id != stream_id
                or stored.stream_version != stream_version
                or stored.event != event
            ):
                raise CommitResultMismatchError(
                    "commit result does not match staged stream event order"
                )
        event_ids = [stored.event_id for stored in result.events]
        if len(event_ids) != len(set(event_ids)):
            raise CommitResultMismatchError(
                "commit result contains duplicate event identities"
            )
        for previous, current in zip(
            result.events,
            result.events[1:],
            strict=False,
        ):
            if current.global_position != previous.global_position + 1:
                raise CommitResultMismatchError(
                    "commit result global positions must be contiguous"
                )

    def _release_all(self) -> None:
        for plan in self._plans:
            if plan.aggregate.is_enlisted:
                AggregateRoot._release(plan.aggregate, self)

    def _fault_all(self) -> None:
        for plan in self._plans:
            if plan.aggregate.is_enlisted:
                AggregateRoot._fault(plan.aggregate, self)

    def _require_active(self, operation: str) -> None:
        if self._state is not _UnitOfWorkState.ACTIVE:
            raise UnitOfWorkLifecycleError(
                f"cannot {operation} Unit of Work in {self._state} state"
            )


class EventSourcedRepository[AggregateIdT, AggregateT: AggregateRoot[Any]]:
    """Load and stage one aggregate category inside an active Unit of Work."""

    def __init__(
        self,
        unit_of_work: EventSourcingUnitOfWork,
        *,
        category: str,
        aggregate_factory: Callable[[AggregateIdT], AggregateT],
        aggregate_type: type[AggregateT],
        id_encoder: Callable[[AggregateIdT], str],
        schemas: EventSchemaRegistry,
        page_size: int | None = None,
        operation_lease: Callable[[], None] | None = None,
    ) -> None:
        if not isinstance(unit_of_work, EventSourcingUnitOfWork):
            raise TypeError("unit_of_work must be EventSourcingUnitOfWork")
        if not schemas.is_frozen:
            raise SchemaRegistryNotFrozenError(
                "repository requires a frozen event schema registry"
            )
        if not isinstance(aggregate_type, type) or not issubclass(
            aggregate_type, AggregateRoot
        ):
            raise TypeError("aggregate_type must be an AggregateRoot subclass")
        if operation_lease is not None and not callable(operation_lease):
            raise TypeError("operation_lease must be callable")
        selected_page_size = (
            schemas.limits.read_page_size if page_size is None else page_size
        )
        if (
            not isinstance(selected_page_size, int)
            or isinstance(selected_page_size, bool)
            or selected_page_size < 1
            or selected_page_size > schemas.limits.read_page_size
        ):
            raise ResourceLimitError(
                "repository page size must be positive and cannot exceed schema limits"
            )
        self._unit_of_work = unit_of_work
        self._category = category
        self._aggregate_factory = aggregate_factory
        self._aggregate_type = aggregate_type
        self._id_encoder = id_encoder
        self._schemas = schemas
        self._page_size = selected_page_size
        self._operation_lease = operation_lease

    async def load(self, aggregate_id: AggregateIdT) -> AggregateT | None:
        """Load an aggregate or return None when its stream is missing."""

        self._require_operation_lease()
        return await self._load(aggregate_id)

    async def _load(self, aggregate_id: AggregateIdT) -> AggregateT | None:
        stream_id = self._stream_id(aggregate_id)
        aggregate = self._new_aggregate(aggregate_id)
        after_version = 0
        found = False
        while True:
            page = await self._unit_of_work.transaction.read_stream(
                stream_id,
                after_version=after_version,
                limit=self._page_size,
            )
            if not page:
                break
            found = True
            recorded = tuple(self._schemas.decode(event) for event in page)
            AggregateRoot._replay(aggregate, recorded)
            after_version = page[-1].stream_version
        return aggregate if found else None

    async def get(self, aggregate_id: AggregateIdT) -> AggregateT:
        """Load an aggregate or raise when its stream is missing."""

        self._require_operation_lease()
        aggregate = await self._load(aggregate_id)
        if aggregate is None:
            raise AggregateNotFoundError(
                f"aggregate stream {self._stream_id(aggregate_id)!r} was not found"
            )
        return aggregate

    def save(self, aggregate: AggregateT) -> None:
        """Encode and stage the aggregate's complete pending event snapshot."""

        self._require_operation_lease()
        if type(aggregate) is not self._aggregate_type:
            raise AggregateTypeMismatchError(
                expected=self._aggregate_type,
                actual=type(aggregate),
            )
        stream_id = self._stream_id(aggregate.id)
        self._unit_of_work.validate_stage(aggregate, stream_id=stream_id)
        pending = aggregate.pending_events
        if not pending:
            return
        append_events = tuple(self._schemas.encode(event) for event in pending)
        self._unit_of_work.stage(
            aggregate,
            stream_id=stream_id,
            pending=pending,
            append_events=append_events,
        )

    def _require_operation_lease(self) -> None:
        """Reject retained-state access when the optional operation lease expires."""

        if self._operation_lease is not None:
            self._operation_lease()

    def _stream_id(self, aggregate_id: AggregateIdT) -> StreamId:
        try:
            key = self._id_encoder(aggregate_id)
        except Exception as error:
            raise RepositoryError("aggregate ID encoder failed") from error
        return StreamId(self._category, key)

    def _new_aggregate(self, aggregate_id: AggregateIdT) -> AggregateT:
        try:
            aggregate = self._aggregate_factory(aggregate_id)
        except Exception as error:
            raise RepositoryError("aggregate factory failed") from error
        if type(aggregate) is not self._aggregate_type:
            raise AggregateTypeMismatchError(
                expected=self._aggregate_type,
                actual=type(aggregate),
            )
        if aggregate.id != aggregate_id:
            raise RepositoryError("aggregate factory returned a different ID")
        return aggregate


__all__ = ["EventSourcedRepository", "EventSourcingUnitOfWork"]
