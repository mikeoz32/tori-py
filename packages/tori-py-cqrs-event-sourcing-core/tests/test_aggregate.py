from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from tori_py_cqrs_core import Event
from tori_py_cqrs_event_sourcing_core import (
    AggregateCommitStateError,
    AggregateEnlistedError,
    AggregateFaultedError,
    AggregateOwnershipError,
    AggregateReplayError,
    AggregateRoot,
    AggregateStreamMismatchError,
    EventMetadata,
    PendingEvent,
    RecordedEvent,
    StreamId,
)


@dataclass(frozen=True, slots=True)
class Opened(Event):
    name: str


@dataclass(frozen=True, slots=True)
class Renamed(Event):
    name: str


@dataclass(frozen=True, slots=True)
class Broken(Event):
    pass


class Profile(AggregateRoot[UUID]):
    def __init__(self, profile_id: UUID) -> None:
        super().__init__(profile_id)
        self.name = ""

    def open(self, name: str, *, metadata: EventMetadata | None = None) -> None:
        self.raise_event(Opened(name), metadata=metadata)

    def rename(self, name: str) -> None:
        self.raise_event(Renamed(name))

    def break_state(self) -> None:
        self.raise_event(Broken())

    def _apply(self, event: Event) -> None:
        match event:
            case Opened(name=name) | Renamed(name=name):
                self.name = name
            case Broken():
                self.name = "partially-mutated"
                raise RuntimeError("broken event")
            case _:
                raise AssertionError(f"unknown event: {event!r}")


def metadata(value: int) -> EventMetadata:
    return EventMetadata(
        event_id=UUID(int=value),
        occurred_at=datetime(2026, 1, value, tzinfo=UTC),
        correlation_id=UUID(int=100 + value),
        headers={"event": str(value)},
    )


def recorded(
    stream: StreamId,
    version: int,
    event: Event,
) -> RecordedEvent:
    return RecordedEvent(
        stream_id=stream,
        stream_version=version,
        global_position=version,
        event_type=f"profile.{type(event).__name__.lower()}",
        schema_version=1,
        event=event,
        metadata=metadata(version),
    )


def test_raise_event_applies_and_records_validated_metadata() -> None:
    profile = Profile(uuid4())
    occurrence = metadata(1)

    profile.open("Alice", metadata=occurrence)

    assert profile.name == "Alice"
    assert profile.version == 0
    assert profile.pending_events == (PendingEvent(Opened("Alice"), occurrence),)
    assert not profile.is_faulted
    assert not profile.is_enlisted


def test_raise_event_assigns_stable_default_metadata_once() -> None:
    profile = Profile(uuid4())

    profile.open("Alice")
    pending = profile.pending_events[0]

    assert isinstance(pending.metadata.event_id, UUID)
    assert pending.metadata.occurred_at.tzinfo is not None
    assert profile.pending_events[0].metadata is pending.metadata


def test_any_apply_failure_faults_the_aggregate() -> None:
    profile = Profile(uuid4())

    with pytest.raises(RuntimeError, match="broken event"):
        profile.break_state()

    assert profile.name == "partially-mutated"
    assert profile.pending_events == ()
    assert profile.is_faulted
    with pytest.raises(AggregateFaultedError):
        profile.rename("unusable")


def test_replay_accepts_finite_contiguous_pages_without_pending_events() -> None:
    stream = StreamId("profile", "42")
    profile = Profile(uuid4())

    profile._replay([recorded(stream, 1, Opened("Alice"))])
    profile._replay([recorded(stream, 2, Renamed("Alicia"))])

    assert profile.name == "Alicia"
    assert profile.version == 2
    assert profile.pending_events == ()


def test_replay_validates_page_before_applying_it() -> None:
    stream = StreamId("profile", "42")
    profile = Profile(uuid4())

    with pytest.raises(AggregateReplayError, match="expected stream version 2"):
        profile._replay(
            [
                recorded(stream, 1, Opened("Alice")),
                recorded(stream, 3, Renamed("invalid")),
            ]
        )

    assert profile.name == ""
    assert profile.version == 0
    assert profile.is_faulted


def test_replay_rejects_mixed_streams_and_faults_on_apply_failure() -> None:
    mixed = Profile(uuid4())
    first = StreamId("profile", "1")
    second = StreamId("profile", "2")

    with pytest.raises(AggregateStreamMismatchError):
        mixed._replay(
            [
                recorded(first, 1, Opened("Alice")),
                recorded(second, 2, Renamed("Alicia")),
            ]
        )
    assert mixed.version == 0
    assert mixed.is_faulted

    profile = Profile(uuid4())
    with pytest.raises(RuntimeError, match="broken event"):
        profile._replay([recorded(first, 1, Broken())])
    assert profile.is_faulted


def test_enlistment_seals_aggregate_and_requires_owner() -> None:
    profile = Profile(uuid4())
    profile.open("Alice", metadata=metadata(1))
    owner = object()
    stream = StreamId("profile", "42")
    snapshot = profile.pending_events

    profile._enlist(owner, stream_id=stream, events=snapshot)

    assert profile.is_enlisted
    with pytest.raises(AggregateEnlistedError):
        profile.rename("blocked")
    with pytest.raises(AggregateEnlistedError):
        profile._enlist(owner, stream_id=stream, events=snapshot)
    with pytest.raises(AggregateOwnershipError):
        profile._release(object())

    profile._release(owner)
    assert not profile.is_enlisted
    assert profile.pending_events == snapshot


def test_commit_is_prevalidated_before_non_failing_transition() -> None:
    profile = Profile(uuid4())
    profile.open("Alice", metadata=metadata(1))
    owner = object()
    stream = StreamId("profile", "42")
    snapshot = profile.pending_events
    profile._enlist(owner, stream_id=stream, events=snapshot)

    with pytest.raises(AggregateCommitStateError, match="committed version"):
        profile._prepare_commit(owner, events=snapshot, version=2)

    transition = profile._prepare_commit(owner, events=snapshot, version=1)
    with pytest.raises(AggregateCommitStateError, match="not prepared"):
        profile._mark_committed(object())
    profile._mark_committed(transition)

    assert profile.version == 1
    assert profile.pending_events == ()
    assert not profile.is_enlisted


def test_fault_retains_pending_events_but_prevents_reuse() -> None:
    profile = Profile(uuid4())
    profile.open("Alice", metadata=metadata(1))
    owner = object()
    snapshot = profile.pending_events
    profile._enlist(owner, stream_id=StreamId("profile", "42"), events=snapshot)

    profile._fault(owner)

    assert profile.pending_events == snapshot
    assert profile.is_faulted
    assert not profile.is_enlisted
    with pytest.raises(AggregateFaultedError):
        profile.rename("blocked")
