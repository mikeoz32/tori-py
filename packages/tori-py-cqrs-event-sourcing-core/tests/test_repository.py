import asyncio
from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass
from typing import Any, cast
from uuid import UUID

import pytest
from tori_py_cqrs_core import Event
from tori_py_cqrs_event_sourcing_core import (
    AggregateCommitStateError,
    AggregateFaultedError,
    AggregateNotFoundError,
    AggregateRoot,
    AggregateTypeMismatchError,
    AppendEvent,
    CommitResult,
    CommitResultMismatchError,
    ConfirmedCommit,
    ConfirmedCommitCleanupError,
    ConfirmedCommitError,
    ConfirmedNonCommit,
    DuplicateAggregateSaveError,
    DuplicateEventIdError,
    DuplicateStreamAggregateError,
    EventSchema,
    EventSchemaRegistry,
    EventSourcedRepository,
    EventSourcingLimits,
    EventSourcingUnitOfWork,
    EventStoreTransactionError,
    IndeterminateCommit,
    IndeterminateCommitError,
    InMemoryEventStore,
    OptimisticConcurrencyError,
    StoredEvent,
    UnitOfWorkLifecycleError,
)


@dataclass(frozen=True, slots=True)
class Opened(Event):
    name: str


@dataclass(frozen=True, slots=True)
class Renamed(Event):
    name: str


@dataclass(frozen=True, slots=True)
class Exploding(Event):
    pass


class Profile(AggregateRoot[UUID]):
    def __init__(self, profile_id: UUID) -> None:
        super().__init__(profile_id)
        self.name = ""

    def open(self, name: str) -> None:
        self.raise_event(Opened(name))

    def rename(self, name: str) -> None:
        self.raise_event(Renamed(name))

    def fail(self) -> None:
        self.raise_event(Exploding())

    def _apply(self, event: Event) -> None:
        match event:
            case Opened(name=name) | Renamed(name=name):
                self.name = name
            case Exploding():
                raise RuntimeError("aggregate application failed")
            case _:
                raise AssertionError(f"unknown event {event!r}")


class OtherProfile(Profile):
    pass


def schemas(*, page_size: int = 500) -> EventSchemaRegistry:
    return (
        EventSchemaRegistry(limits=EventSourcingLimits(read_page_size=page_size))
        .register(
            EventSchema(
                "profile.opened",
                1,
                Opened,
                lambda event: event.name.encode(),
                lambda payload: Opened(payload.decode()),
            )
        )
        .register(
            EventSchema(
                "profile.renamed",
                1,
                Renamed,
                lambda event: event.name.encode(),
                lambda payload: Renamed(payload.decode()),
            )
        )
        .freeze()
    )


def repository(
    unit_of_work: EventSourcingUnitOfWork,
    registry: EventSchemaRegistry,
    *,
    operation_lease: Callable[[], None] | None = None,
) -> EventSourcedRepository[UUID, Profile]:
    return EventSourcedRepository(
        unit_of_work,
        category="profile",
        aggregate_factory=Profile,
        aggregate_type=Profile,
        id_encoder=str,
        schemas=registry,
        operation_lease=operation_lease,
    )


@pytest.mark.asyncio
async def test_create_commit_and_reload_aggregate_from_events() -> None:
    store = InMemoryEventStore()
    registry = schemas()
    profile_id = UUID(int=1)

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        profiles = repository(unit_of_work, registry)
        profile = Profile(profile_id)
        profile.open("Alice")
        profile.rename("Alicia")
        profiles.save(profile)
        result = await unit_of_work.commit()

    assert profile.version == 2
    assert profile.pending_events == ()
    assert [event.stream_version for event in result.events] == [1, 2]
    assert unit_of_work.outcome == ConfirmedCommit(result)

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        loaded = await repository(unit_of_work, registry).get(profile_id)

    assert loaded.name == "Alicia"
    assert loaded.version == 2
    assert loaded.pending_events == ()


@pytest.mark.asyncio
async def test_optional_and_required_missing_loads() -> None:
    store = InMemoryEventStore()
    registry = schemas()
    profile_id = UUID(int=1)

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        profiles = repository(unit_of_work, registry)
        assert await profiles.load(profile_id) is None
        with pytest.raises(AggregateNotFoundError):
            await profiles.get(profile_id)


@pytest.mark.asyncio
async def test_repository_replays_finite_pages_from_one_snapshot() -> None:
    registry = schemas(page_size=1)
    store = InMemoryEventStore(limits=registry.limits)
    profile_id = UUID(int=1)
    async with EventSourcingUnitOfWork(store) as unit_of_work:
        profile = Profile(profile_id)
        profile.open("Alice")
        profile.rename("Alicia")
        repository(unit_of_work, registry).save(profile)
        await unit_of_work.commit()

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        loaded = await repository(unit_of_work, registry).get(profile_id)

    assert loaded.name == "Alicia"
    assert loaded.version == 2


@pytest.mark.asyncio
async def test_no_pending_save_is_a_no_op() -> None:
    store = InMemoryEventStore()
    registry = schemas()
    profile = Profile(UUID(int=1))

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repository(unit_of_work, registry).save(profile)
        result = await unit_of_work.commit()

    assert result == CommitResult(())


@pytest.mark.asyncio
async def test_repeated_save_and_duplicate_stream_instance_are_rejected() -> None:
    store = InMemoryEventStore()
    registry = schemas()
    profile_id = UUID(int=1)
    first = Profile(profile_id)
    first.open("Alice")
    second = Profile(profile_id)
    second.open("Other")

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        profiles = repository(unit_of_work, registry)
        profiles.save(first)
        with pytest.raises(DuplicateAggregateSaveError):
            profiles.save(first)
        with pytest.raises(DuplicateStreamAggregateError):
            profiles.save(second)


@pytest.mark.asyncio
async def test_context_exit_and_explicit_rollback_release_pending_aggregate() -> None:
    store = InMemoryEventStore()
    registry = schemas()
    profile = Profile(UUID(int=1))
    profile.open("Alice")

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repository(unit_of_work, registry).save(profile)

    assert unit_of_work.outcome == ConfirmedNonCommit()
    assert not profile.is_enlisted
    assert profile.pending_events
    assert not profile.is_faulted

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repository(unit_of_work, registry).save(profile)
        await unit_of_work.rollback()

    assert unit_of_work.outcome == ConfirmedNonCommit()
    assert not profile.is_enlisted
    assert profile.pending_events


@pytest.mark.asyncio
async def test_multi_aggregate_commit_is_atomic() -> None:
    store = InMemoryEventStore()
    registry = schemas()
    first = Profile(UUID(int=1))
    second = Profile(UUID(int=2))
    first.open("Alice")
    second.open("Bob")

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        profiles = repository(unit_of_work, registry)
        profiles.save(first)
        profiles.save(second)
        await unit_of_work.commit()

    assert first.version == second.version == 1
    assert len(await store.read_all(limit=10)) == 2


@pytest.mark.asyncio
async def test_optimistic_conflict_faults_every_enlisted_aggregate() -> None:
    store = InMemoryEventStore()
    registry = schemas()
    first_id = UUID(int=1)
    second_id = UUID(int=2)
    async with EventSourcingUnitOfWork(store) as initial:
        profiles = repository(initial, registry)
        first = Profile(first_id)
        second = Profile(second_id)
        first.open("Alice")
        second.open("Bob")
        profiles.save(first)
        profiles.save(second)
        await initial.commit()

    stale = EventSourcingUnitOfWork(store)
    winner = EventSourcingUnitOfWork(store)
    async with stale, winner:
        stale_profiles = repository(stale, registry)
        winner_profiles = repository(winner, registry)
        stale_first = await stale_profiles.get(first_id)
        stale_second = await stale_profiles.get(second_id)
        winning_first = await winner_profiles.get(first_id)
        stale_first.rename("stale")
        stale_second.rename("also-stale")
        winning_first.rename("winner")
        stale_profiles.save(stale_first)
        stale_profiles.save(stale_second)
        winner_profiles.save(winning_first)
        await winner.commit()

        with pytest.raises(OptimisticConcurrencyError):
            await stale.commit()

    assert isinstance(stale.outcome, ConfirmedNonCommit)
    assert isinstance(stale.outcome.cause, OptimisticConcurrencyError)
    assert stale_first.is_faulted
    assert stale_second.is_faulted
    assert stale_first.pending_events
    assert stale_second.pending_events


class _ResultTransaction:
    def __init__(
        self,
        outcome,
        *,
        rollback_error: BaseException | None = None,
    ) -> None:
        self.outcome = outcome
        self.rollback_error = rollback_error
        self.appended: tuple[AppendEvent, ...] = ()
        self.stream_id = None
        self.expected_version = 0

    async def read_stream(self, stream_id, *, after_version=0, limit):
        return ()

    def append(self, stream_id, *, expected_version, events) -> None:
        self.stream_id = stream_id
        self.expected_version = expected_version
        self.appended = events

    async def commit(self) -> CommitResult:
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if callable(self.outcome):
            return self.outcome(self)
        return self.outcome

    async def rollback(self) -> None:
        if self.rollback_error is not None:
            raise self.rollback_error
        return None


class _ResultContext:
    def __init__(
        self,
        transaction: _ResultTransaction,
        *,
        cleanup_error: BaseException | None = None,
    ) -> None:
        self.transaction = transaction
        self.cleanup_error = cleanup_error
        self.exited = False

    async def __aenter__(self):
        return self.transaction

    async def __aexit__(self, error_type, error, traceback):
        self.exited = True
        if self.cleanup_error is not None:
            raise self.cleanup_error
        return None


class _ResultStore:
    def __init__(
        self,
        outcome,
        *,
        rollback_error: BaseException | None = None,
        cleanup_error: BaseException | None = None,
    ) -> None:
        self.inner = _ResultTransaction(outcome, rollback_error=rollback_error)
        self.context = _ResultContext(self.inner, cleanup_error=cleanup_error)

    async def read_stream(self, stream_id, *, after_version=0, limit):
        return ()

    async def read_all(self, *, after_position=0, limit):
        return ()

    def transaction(self):
        return self.context


class _EntryFailureStore(_ResultStore):
    def __init__(self, error: BaseException) -> None:
        super().__init__(CommitResult(()))
        self.error = error

    def transaction(self):
        raise self.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "error_type"),
    [
        (CommitResult(()), CommitResultMismatchError),
        (IndeterminateCommitError("unknown"), IndeterminateCommitError),
    ],
)
async def test_unknown_or_malformed_commit_faults_aggregate(
    outcome,
    error_type,
) -> None:
    store = _ResultStore(outcome)
    profile = Profile(UUID(int=1))
    profile.open("Alice")

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repository(unit_of_work, schemas()).save(profile)
        with pytest.raises(error_type) as failure:
            await unit_of_work.commit()

    assert unit_of_work.outcome == IndeterminateCommit(failure.value)
    assert profile.is_faulted
    assert profile.pending_events


@pytest.mark.asyncio
async def test_confirmed_precommit_failure_releases_aggregate() -> None:
    store = _ResultStore(ConfirmedCommitError("definite failure"))
    profile = Profile(UUID(int=1))
    profile.open("Alice")

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repository(unit_of_work, schemas()).save(profile)
        with pytest.raises(ConfirmedCommitError) as failure:
            await unit_of_work.commit()

    assert unit_of_work.outcome == ConfirmedNonCommit(failure.value)
    assert not profile.is_faulted
    assert not profile.is_enlisted
    assert profile.pending_events
    with pytest.raises(UnitOfWorkLifecycleError):
        await unit_of_work.commit()


@pytest.mark.asyncio
async def test_unknown_failure_faults_aggregate() -> None:
    store = _ResultStore(EventStoreTransactionError("unclassified failure"))
    profile = Profile(UUID(int=1))
    profile.open("Alice")

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repository(unit_of_work, schemas()).save(profile)
        with pytest.raises(EventStoreTransactionError) as failure:
            await unit_of_work.commit()

    assert unit_of_work.outcome == IndeterminateCommit(failure.value)
    assert profile.is_faulted
    assert profile.pending_events


@pytest.mark.asyncio
async def test_known_rollback_cancellation_releases_aggregate() -> None:
    store = _ResultStore(asyncio.CancelledError())
    profile = Profile(UUID(int=1))
    profile.open("Alice")

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repository(unit_of_work, schemas()).save(profile)
        with pytest.raises(asyncio.CancelledError) as failure:
            await unit_of_work.commit()

    assert unit_of_work.outcome == ConfirmedNonCommit(failure.value)
    assert not profile.is_faulted
    assert not profile.is_enlisted
    assert profile.pending_events


@pytest.mark.asyncio
async def test_in_memory_lock_wait_cancellation_releases_aggregate() -> None:
    store = InMemoryEventStore()
    profile = Profile(UUID(int=1))
    profile.open("Alice")

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repository(unit_of_work, schemas()).save(profile)
        await store._lock.acquire()
        task = asyncio.create_task(unit_of_work.commit())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        store._lock.release()

    assert not profile.is_faulted
    assert not profile.is_enlisted
    assert profile.pending_events


@pytest.mark.asyncio
async def test_malformed_global_positions_fault_aggregate() -> None:
    def malformed(transaction: _ResultTransaction) -> CommitResult:
        assert transaction.stream_id is not None
        return CommitResult(
            tuple(
                StoredEvent(
                    transaction.stream_id,
                    stream_version=offset,
                    global_position=1,
                    event=event,
                )
                for offset, event in enumerate(transaction.appended, start=1)
            )
        )

    store = _ResultStore(malformed)
    profile = Profile(UUID(int=1))
    profile.open("Alice")
    profile.rename("Alicia")

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repository(unit_of_work, schemas()).save(profile)
        with pytest.raises(
            CommitResultMismatchError, match="global positions"
        ) as failure:
            await unit_of_work.commit()

    assert unit_of_work.outcome == IndeterminateCommit(failure.value)
    assert profile.is_faulted


@pytest.mark.asyncio
async def test_repository_rejects_wrong_aggregate_type_before_encoding() -> None:
    calls = 0

    def encode(event: Opened) -> bytes:
        nonlocal calls
        calls += 1
        return event.name.encode()

    registry = (
        EventSchemaRegistry()
        .register(
            EventSchema(
                "profile.opened",
                1,
                Opened,
                encode,
                lambda payload: Opened(payload.decode()),
            )
        )
        .freeze()
    )
    store = InMemoryEventStore()
    other = OtherProfile(UUID(int=1))
    other.open("Alice")

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        profiles = repository(unit_of_work, registry)
        with pytest.raises(AggregateTypeMismatchError):
            profiles.save(cast(Any, other))

    assert calls == 0

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        invalid_factory = EventSourcedRepository(
            unit_of_work,
            category="profile",
            aggregate_factory=cast(Any, OtherProfile),
            aggregate_type=Profile,
            id_encoder=str,
            schemas=registry,
        )
        with pytest.raises(AggregateTypeMismatchError):
            await invalid_factory.load(UUID(int=2))


@pytest.mark.asyncio
async def test_rejected_lifecycle_saves_do_not_run_encoder() -> None:
    calls = 0

    def encode(event: Opened) -> bytes:
        nonlocal calls
        calls += 1
        return event.name.encode()

    registry = (
        EventSchemaRegistry()
        .register(
            EventSchema(
                "profile.opened",
                1,
                Opened,
                encode,
                lambda payload: Opened(payload.decode()),
            )
        )
        .freeze()
    )
    store = InMemoryEventStore()
    first = Profile(UUID(int=1))
    first.open("Alice")
    duplicate = Profile(UUID(int=1))
    duplicate.open("Other")

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        profiles = repository(unit_of_work, registry)
        profiles.save(first)
        assert calls == 1
        with pytest.raises(DuplicateAggregateSaveError):
            profiles.save(first)
        with pytest.raises(DuplicateStreamAggregateError):
            profiles.save(duplicate)
        assert calls == 1

    faulted = Profile(UUID(int=2))
    with pytest.raises(RuntimeError):
        faulted.fail()
    async with EventSourcingUnitOfWork(store) as unit_of_work:
        with pytest.raises(AggregateFaultedError, match="faulted"):
            repository(unit_of_work, registry).save(faulted)
    assert calls == 1


@pytest.mark.asyncio
async def test_rollback_failure_still_exits_owned_transaction_context() -> None:
    store = _ResultStore(
        CommitResult(()),
        rollback_error=RuntimeError("rollback failed"),
        cleanup_error=RuntimeError("cleanup failed"),
    )
    profile = Profile(UUID(int=1))
    profile.open("Alice")

    with pytest.raises(RuntimeError, match="rollback failed"):
        async with EventSourcingUnitOfWork(store) as unit_of_work:
            repository(unit_of_work, schemas()).save(profile)

    assert store.context.exited
    assert profile.is_faulted
    assert isinstance(unit_of_work.outcome, ConfirmedNonCommit)
    assert unit_of_work.outcome.cause is not None
    assert str(unit_of_work.outcome.cause) == "rollback failed"


@pytest.mark.asyncio
async def test_committing_uow_rejects_stage_rollback_and_second_commit() -> None:
    store = InMemoryEventStore()
    registry = schemas()
    first = Profile(UUID(int=1))
    first.open("Alice")
    second = Profile(UUID(int=2))
    second.open("Bob")

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        profiles = repository(unit_of_work, registry)
        profiles.save(first)
        await store._lock.acquire()
        committing = asyncio.create_task(unit_of_work.commit())
        await asyncio.sleep(0)
        with pytest.raises(UnitOfWorkLifecycleError, match="committing"):
            profiles.save(second)
        with pytest.raises(UnitOfWorkLifecycleError, match="committing"):
            await unit_of_work.rollback()
        with pytest.raises(UnitOfWorkLifecycleError, match="committing"):
            await unit_of_work.commit()
        with pytest.raises(UnitOfWorkLifecycleError, match="committing"):
            _ = unit_of_work.outcome
        store._lock.release()
        await committing

    assert first.version == 1
    assert not second.is_enlisted
    assert second.pending_events


@pytest.mark.asyncio
async def test_cleanup_failure_after_commit_carries_confirmed_result() -> None:
    def confirmed(transaction: _ResultTransaction) -> CommitResult:
        assert transaction.stream_id is not None
        return CommitResult(
            tuple(
                StoredEvent(
                    transaction.stream_id,
                    stream_version=offset,
                    global_position=offset,
                    event=event,
                )
                for offset, event in enumerate(transaction.appended, start=1)
            )
        )

    store = _ResultStore(
        confirmed,
        cleanup_error=RuntimeError("connection cleanup failed"),
    )
    profile = Profile(UUID(int=1))
    profile.open("Alice")

    with pytest.raises(ConfirmedCommitCleanupError) as failure:
        async with EventSourcingUnitOfWork(store) as unit_of_work:
            repository(unit_of_work, schemas()).save(profile)
            result = await unit_of_work.commit()

    assert failure.value.result is result
    assert unit_of_work.outcome == ConfirmedCommit(result)
    assert profile.version == 1
    assert profile.pending_events == ()


@pytest.mark.asyncio
async def test_entering_uow_rejects_second_entry() -> None:
    store = InMemoryEventStore()
    unit_of_work = EventSourcingUnitOfWork(store)
    await store._lock.acquire()
    entering = asyncio.create_task(unit_of_work.__aenter__())
    await asyncio.sleep(0)
    with pytest.raises(UnitOfWorkLifecycleError, match="entering"):
        await unit_of_work.__aenter__()
    store._lock.release()
    assert await entering is unit_of_work
    await unit_of_work.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_outcome_is_read_only_immutable_and_unavailable_until_final() -> None:
    store = InMemoryEventStore()
    unit_of_work = EventSourcingUnitOfWork(store)

    with pytest.raises(UnitOfWorkLifecycleError, match="new"):
        _ = unit_of_work.outcome
    async with unit_of_work:
        with pytest.raises(UnitOfWorkLifecycleError, match="active"):
            _ = unit_of_work.outcome
        result = await unit_of_work.commit()

    outcome = unit_of_work.outcome
    assert outcome == ConfirmedCommit(result)
    with pytest.raises(AttributeError):
        setattr(unit_of_work, "outcome", outcome)  # noqa: B010
    with pytest.raises(FrozenInstanceError):
        setattr(outcome, "result", CommitResult(()))  # noqa: B010


@pytest.mark.asyncio
async def test_transaction_entry_failure_is_a_confirmed_non_commit() -> None:
    error = RuntimeError("transaction entry failed")
    unit_of_work = EventSourcingUnitOfWork(_EntryFailureStore(error))

    with pytest.raises(RuntimeError) as failure:
        await unit_of_work.__aenter__()

    assert failure.value is error
    assert unit_of_work.outcome == ConfirmedNonCommit(error)


@pytest.mark.asyncio
async def test_context_rollback_outcome_retains_body_error() -> None:
    error = RuntimeError("handler failed")
    unit_of_work = EventSourcingUnitOfWork(InMemoryEventStore())

    with pytest.raises(RuntimeError) as failure:
        async with unit_of_work:
            raise error

    assert failure.value is error
    assert unit_of_work.outcome == ConfirmedNonCommit(error)


@pytest.mark.asyncio
async def test_duplicate_event_id_is_a_confirmed_non_commit() -> None:
    error = DuplicateEventIdError(event_id=UUID(int=10))
    store = _ResultStore(error)
    profile = Profile(UUID(int=1))
    profile.open("Alice")

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repository(unit_of_work, schemas()).save(profile)
        with pytest.raises(DuplicateEventIdError):
            await unit_of_work.commit()

    assert unit_of_work.outcome == ConfirmedNonCommit(error)
    assert profile.is_faulted


@pytest.mark.asyncio
async def test_precommit_validation_failure_is_a_confirmed_non_commit() -> None:
    profile = Profile(UUID(int=1))
    profile.open("Alice")

    async with EventSourcingUnitOfWork(InMemoryEventStore()) as unit_of_work:
        repository(unit_of_work, schemas()).save(profile)
        cast(Any, profile)._pending_events.clear()
        with pytest.raises(AggregateCommitStateError) as failure:
            await unit_of_work.commit()

    assert unit_of_work.outcome == ConfirmedNonCommit(failure.value)
    assert profile.is_faulted


class _LeaseError(RuntimeError):
    pass


@pytest.mark.asyncio
async def test_operation_lease_checks_each_public_load_and_save_operation() -> None:
    calls = 0

    def require_lease() -> None:
        nonlocal calls
        calls += 1

    registry = schemas()
    profile_id = UUID(int=1)
    profile = Profile(profile_id)
    profile.open("Alice")
    async with EventSourcingUnitOfWork(InMemoryEventStore()) as unit_of_work:
        profiles = repository(
            unit_of_work,
            registry,
            operation_lease=require_lease,
        )
        assert await profiles.load(profile_id) is None
        with pytest.raises(AggregateNotFoundError):
            await profiles.get(profile_id)
        profiles.save(profile)

    assert calls == 3


@pytest.mark.asyncio
async def test_operation_lease_failure_precedes_load_and_save_side_effects() -> None:
    error = _LeaseError("transaction lease expired")
    encoder_calls = 0
    factory_calls = 0

    def reject() -> None:
        raise error

    def id_encoder(aggregate_id: UUID) -> str:
        nonlocal encoder_calls
        encoder_calls += 1
        return str(aggregate_id)

    def aggregate_factory(aggregate_id: UUID) -> Profile:
        nonlocal factory_calls
        factory_calls += 1
        return Profile(aggregate_id)

    profile = Profile(UUID(int=1))
    profile.open("Alice")
    unit_of_work = EventSourcingUnitOfWork(InMemoryEventStore())
    profiles = EventSourcedRepository(
        unit_of_work,
        category="profile",
        aggregate_factory=aggregate_factory,
        aggregate_type=Profile,
        id_encoder=id_encoder,
        schemas=schemas(),
        operation_lease=reject,
    )

    with pytest.raises(_LeaseError) as load_failure:
        await profiles.load(profile.id)
    with pytest.raises(_LeaseError) as get_failure:
        await profiles.get(profile.id)
    with pytest.raises(_LeaseError) as save_failure:
        profiles.save(profile)

    assert load_failure.value is error
    assert get_failure.value is error
    assert save_failure.value is error
    assert encoder_calls == factory_calls == 0
    assert not profile.is_enlisted
    assert profile.pending_events
    with pytest.raises(UnitOfWorkLifecycleError, match="new"):
        _ = unit_of_work.outcome


def test_custom_repository_can_require_operation_lease() -> None:
    error = _LeaseError("transaction lease expired")

    def reject() -> None:
        raise error

    class Profiles(EventSourcedRepository[UUID, Profile]):
        def custom_operation(self) -> None:
            self._require_operation_lease()

    profiles = Profiles(
        EventSourcingUnitOfWork(InMemoryEventStore()),
        category="profile",
        aggregate_factory=Profile,
        aggregate_type=Profile,
        id_encoder=str,
        schemas=schemas(),
        operation_lease=reject,
    )

    with pytest.raises(_LeaseError) as failure:
        profiles.custom_operation()
    assert failure.value is error
