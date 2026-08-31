# Stores, Repositories, and Unit of Work

`tori-py-cqrs-event-sourcing-core` defines an asynchronous event-store boundary,
an atomic in-memory reference implementation, event-sourced repositories, and an
explicit Unit of Work. It does not choose a database or commit automatically.

This guide assumes the aggregate and frozen schema registry from
[Aggregates and Event Schemas](aggregates-and-schemas.md).

## Store Protocols

Applications and adapters program against two runtime-checkable public
protocols:

```python
from tori_py_cqrs_event_sourcing_core import EventStore, EventStoreTransaction


assert isinstance(store, EventStore)
```

`EventStore` exposes:

```python
await store.read_stream(stream_id, after_version=0, limit=100)
await store.read_all(after_position=0, limit=100)
store.transaction()  # async context manager
```

`EventStoreTransaction` exposes:

```python
await transaction.read_stream(stream_id, after_version=0, limit=100)
transaction.append(stream_id, expected_version=3, events=append_events)
await transaction.commit()
await transaction.rollback()
```

Every read has a positive finite limit. `after_version` and `after_position` are
non-negative exclusive cursors. A missing stream returns an empty tuple.

## Transaction Snapshot

The minimum isolation contract is a repeatable committed snapshot established
when the transaction context enters:

- repeated reads in one transaction see the same committed stream data;
- commits made by other transactions after entry are not visible;
- a transaction's own staged appends are not visible to its reads;
- expected versions are checked against current committed state at commit time;
- all staged stream batches commit atomically or none do.

This does not promise serializable predicate reads or prevent write skew across
unrelated streams. Put invariants that must conflict together in one aggregate
stream, or require a stronger separately specified production adapter profile.

Leaving an active transaction context without committing rolls it back. Commit
and rollback are terminal; closed transactions reject unsupported further use.

## Direct Store Append

Repositories are the normal aggregate API, but direct append is useful for
adapter tests, migrations, and inserting a known historical encoded event:

```python
from datetime import UTC, datetime
from uuid import uuid4

from tori_py_cqrs_event_sourcing_core import (
    AppendEvent,
    EncodedEvent,
    EventMetadata,
    InMemoryEventStore,
    StreamId,
)


store = InMemoryEventStore()
stream_id = StreamId("profile", "42")
event = AppendEvent(
    encoded=EncodedEvent(
        event_type="profile.opened",
        schema_version=1,
        payload=b'{"display_name":"Alice"}',
    ),
    metadata=EventMetadata(
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
    ),
)

async with store.transaction() as transaction:
    transaction.append(
        stream_id,
        expected_version=0,
        events=(event,),
    )
    result = await transaction.commit()

assert result.events[0].stream_version == 1
assert result.events[0].global_position == 1
```

An append batch must be non-empty and within configured limits. One transaction
may stage several streams, but only one batch per stream. Event IDs must be
unique within a batch, across staged batches, and against committed storage.

Commit assigns versions in event order and global positions in transaction
staging order. `CommitResult.events` retains that complete order, and
`result.final_version(stream_id)` returns the final version assigned to a stream
or `None` when the result contains no event for it.

## In-Memory Event Store

`InMemoryEventStore` is an atomic semantic reference and test fixture:

```python
from tori_py_cqrs_event_sourcing_core import EventSourcingLimits, InMemoryEventStore


limits = EventSourcingLimits(read_page_size=100)
store = InMemoryEventStore(limits=limits)
```

It keeps immutable committed state per store instance and serializes commit
validation through an async lock. Before mutating state, it validates every
expected stream version and every event ID. A failure therefore cannot expose a
partial multi-stream commit.

The implementation supplies one deterministic global order. It is not durable:
process exit loses all records, and it provides no outbox, migration, backup,
replication, or distributed ordering guarantee.

## Construct a Repository

An `EventSourcedRepository` binds one aggregate category and one active Unit of
Work transaction:

```python
from tori_py_cqrs_event_sourcing_core import EventSourcedRepository


def profile_repository(unit_of_work):
    return EventSourcedRepository(
        unit_of_work,
        category="profile",
        aggregate_factory=Profile,
        aggregate_type=Profile,
        id_encoder=str,
        schemas=schemas,
        page_size=100,
    )
```

The schema registry must already be frozen. `aggregate_factory(id)` must return
the exact configured aggregate type with exactly that ID. Subclasses are not
accepted as substitutes. The ID encoder must return a stable string suitable for
`StreamId(category, key)`.

When `page_size` is omitted, the repository uses the registry limit. An explicit
size must be positive and no greater than `schemas.limits.read_page_size`.

## Load and Replay

`load(id)` is optional and `get(id)` is required:

```python
profile = await profiles.load(profile_id)
if profile is None:
    profile = Profile(profile_id)

required = await profiles.get(profile_id)  # AggregateNotFoundError if absent
```

Both operations derive the stream ID, create a pristine aggregate, read the
complete stream in finite pages from the Unit of Work's repeatable snapshot,
decode/upcast each page, and replay it. A returned aggregate has:

- state derived only from committed events;
- `version` equal to the last replayed stream version;
- no pending events;
- association with that one stream.

Malformed storage, codec failures, non-contiguous versions, mixed streams, or
event-application failures propagate as typed errors. A partially replayed
aggregate is faulted and never returned.

## Save and Stage

Repository `save()` is synchronous because encoding and transaction staging are
synchronous in the contract:

```python
profile.change_display_name("Alicia")
profiles.save(profile)
```

Save performs these steps:

1. Check an optional operation lease.
2. Require the exact configured aggregate type.
3. Derive and validate the stream ID.
4. Reject a faulted or already enlisted aggregate.
5. Reject an aggregate that already has a staged save in the Unit of Work.
6. Reject another aggregate instance targeting an already staged stream.
7. Capture the complete pending-event tuple.
8. Return without enlistment when that tuple is empty; repeated no-op saves
   remain valid.
9. Encode each event while retaining occurrence metadata.
10. Enlist and seal the aggregate.
11. Stage one append at `expected_version=aggregate.version`.

Lifecycle and duplicate checks happen before event encoders, so rejected saves
do not trigger serialization side effects. Encoding does not clear pending
events. Once staged, the aggregate cannot be mutated until finalization.

If staging itself fails, the repository releases the enlistment and retains the
pending events. The surrounding Unit of Work still owns transaction cleanup.

## Basic Unit-of-Work Flow

The Unit of Work creates and owns one event-store transaction:

```python
from tori_py_cqrs_event_sourcing_core import EventSourcingUnitOfWork


async with EventSourcingUnitOfWork(store) as unit_of_work:
    profiles = profile_repository(unit_of_work)
    profile = await profiles.load(profile_id)
    if profile is None:
        profile = Profile(profile_id)
        profile.open("Alice")
    else:
        profile.change_display_name("Alicia")

    profiles.save(profile)
    result = await unit_of_work.commit()

assert profile.version == result.final_version(StreamId("profile", str(profile_id)))
assert profile.pending_events == ()
```

The context manager does not auto-commit. If the active scope exits without a
successful `commit()`, it rolls back and releases reusable aggregates while
retaining their pending events.

`commit()`:

1. Enters the committing state synchronously.
2. Validates every aggregate's ownership, exact pending snapshot, expected
   version, and final local transition before storage I/O.
3. Awaits the transaction's atomic commit.
4. Validates the returned `CommitResult` against every staged stream/event in
   exact order, including event IDs and contiguous global positions.
5. Records `ConfirmedCommit`.
6. Advances every aggregate to its final version and clears its exact pending
   snapshot.

A commit with no staged events is valid and returns `CommitResult(())`.

While commit is in progress, transaction access, staging, rollback, another
commit, and outcome inspection are rejected with `UnitOfWorkLifecycleError`.

## Atomic Multi-Aggregate Commit

One Unit of Work can stage one aggregate per stream across several repositories:

```python
async with EventSourcingUnitOfWork(store) as unit_of_work:
    profiles = profile_repository(unit_of_work)
    first = Profile(first_id)
    second = Profile(second_id)
    first.open("Alice")
    second.open("Bob")
    profiles.save(first)
    profiles.save(second)
    await unit_of_work.commit()
```

The store commits all staged streams or none. This is atomic only within one
`EventStore` transaction. There is no cross-store, database-plus-broker, or
distributed transaction.

## Optimistic Concurrency

Expected versions are checked at commit, so two repeatable snapshots can load
the same stream version:

```python
from tori_py_cqrs_event_sourcing_core import OptimisticConcurrencyError


first = EventSourcingUnitOfWork(store)
second = EventSourcingUnitOfWork(store)

async with first, second:
    first_profiles = profile_repository(first)
    second_profiles = profile_repository(second)
    first_profile = await first_profiles.get(profile_id)
    second_profile = await second_profiles.get(profile_id)

    first_profile.change_display_name("First")
    second_profile.change_display_name("Second")
    first_profiles.save(first_profile)
    second_profiles.save(second_profile)

    await first.commit()
    try:
        await second.commit()
    except OptimisticConcurrencyError as error:
        assert error.expected_version < error.actual_version
```

The second outcome is a confirmed non-commit, but the stale aggregate is
faulted. Its pending events remain for diagnostics, not reuse. If a Unit of Work
staged several aggregates, an optimistic conflict or duplicate event ID faults
all of them because their atomic decision set is stale.

Reload current state in a new Unit of Work and make a new decision. Do not simply
resubmit retained bytes.

## Final Outcomes

`unit_of_work.outcome` is available only after a final classification. Access in
new, entering, active, or committing state raises `UnitOfWorkLifecycleError`.

```python
from tori_py_cqrs_event_sourcing_core import (
    ConfirmedCommit,
    ConfirmedNonCommit,
    IndeterminateCommit,
)


match unit_of_work.outcome:
    case ConfirmedCommit(result=result):
        print("committed", len(result.events))
    case ConfirmedNonCommit(cause=cause):
        print("not committed", cause)
    case IndeterminateCommit(cause=cause):
        print("reconciliation required", cause)
```

The values are immutable. The cause is the original exception where one exists.

### Classification matrix

| Situation | Outcome | Aggregate state |
| --- | --- | --- |
| Validated commit result | `ConfirmedCommit(result)` | Version advanced; staged pending events cleared |
| Explicit rollback or context exit without commit | `ConfirmedNonCommit(cause)` | Released; pending events retained |
| Transaction entry failure | `ConfirmedNonCommit(error)` | No aggregate enlisted |
| Handler/application failure causing context rollback | `ConfirmedNonCommit(error)` | Released if rollback succeeds |
| `OptimisticConcurrencyError` | `ConfirmedNonCommit(error)` | Every enlisted aggregate faulted |
| `DuplicateEventIdError` during commit | `ConfirmedNonCommit(error)` | Every enlisted aggregate faulted |
| Adapter `ConfirmedCommitError` proving no storage mutation | `ConfirmedNonCommit(error)` | Released; pending events retained |
| Raw commit `CancelledError` with adapter-confirmed rollback | `ConfirmedNonCommit(error)` | Released; pending events retained |
| Pre-commit aggregate-plan validation failure | `ConfirmedNonCommit(error)` | Every enlisted aggregate faulted |
| `IndeterminateCommitError` | `IndeterminateCommit(error)` | Every enlisted aggregate faulted |
| Unknown failure after commit starts | `IndeterminateCommit(error)` | Every enlisted aggregate faulted |
| Malformed or mismatched `CommitResult` | `IndeterminateCommit(error)` | Every enlisted aggregate faulted |

`ConfirmedNonCommit` does not always mean the same in-memory aggregate can be
retried. Conflicts, duplicate event IDs, and invalid commit plans prove the
tracked state is stale or unsafe and fault it. Inspect the typed exception and
reload when required.

## Indeterminate Commit

A production adapter can lose connection or receive cancellation after its
database durably commits but before confirmation reaches Python. It must raise
`IndeterminateCommitError`, not `CancelledError` or a generic confirmed failure.

The Unit of Work then:

- does not mark aggregates committed;
- faults all enlisted aggregates;
- preserves pending events only for diagnosis;
- records `IndeterminateCommit(cause)`;
- re-raises the original commit failure.

Do not automatically retry the command or append the same pending batch. Query
the authoritative store by event ID, stream version, and an application command
idempotency key. The correct recovery may be "already committed", "not
committed", or manual reconciliation. Exactly-once command execution is not
provided by event IDs and expected versions alone.

Adapter authors must reserve raw commit `CancelledError` for a known non-commit.
If cancellation crosses an acknowledgement boundary and the outcome is unknown,
translate it to `IndeterminateCommitError`.

## Cleanup After Commit

The store transaction context can fail while closing after a validated commit.
The Unit of Work preserves the committed fact and raises
`ConfirmedCommitCleanupError` carrying:

- `result`: the confirmed `CommitResult`;
- `cleanup_error`: the original cleanup failure.

`unit_of_work.outcome` remains `ConfirmedCommit(result)`, and aggregates already
have advanced versions and cleared pending events. Never present this error as a
normal rollback or automatically retry the command.

## Repository Operation Leases

Framework integrations can supply a synchronous lease check:

```python
def require_active_operation() -> None:
    if not operation_is_active:
        raise RuntimeError("repository operation lease expired")


profiles = EventSourcedRepository(
    unit_of_work,
    category="profile",
    aggregate_factory=Profile,
    aggregate_type=Profile,
    id_encoder=str,
    schemas=schemas,
    operation_lease=require_active_operation,
)
```

Every public `load()`, `get()`, and `save()` checks the lease before touching the
ID encoder, aggregate factory, transaction, encoder, or aggregate state. Lease
errors propagate unchanged.

A custom repository method that uses only guarded base methods inherits their
checks. A custom method touching retained transaction or aggregate state
directly must call `self._require_operation_lease()` first. Omitting a lease
preserves standalone repository behavior.

The ToriPy integration uses this hook to reject escaped repositories, child-task
access, and use after the command handler body.

## Global Reads and Projections

`read_all()` exposes finite pages in committed global order for projection code:

```python
checkpoint = 0
while True:
    page = await store.read_all(after_position=checkpoint, limit=100)
    if not page:
        break
    for stored in page:
        recorded = schemas.decode(stored)
        projection.apply(recorded)
        checkpoint = stored.global_position
```

The package does not persist `checkpoint`, make `projection.apply()` idempotent,
retry poison events, or run this loop in the background. A production projector
must atomically coordinate its read-model update and durable checkpoint or use
an equivalent idempotent design.

## No Automatic Event Publication

Committing to `EventStore` never calls CQRS `EventBus`. Reading from `read_all()`
is a pull-based committed feed, not transport delivery. If reliable publication
is required, a production store adapter must write event and outbox records in
the same database transaction, and a separate relay must publish them.

An in-process post-commit callback can reduce ordering mistakes but cannot close
the process-crash window between commit and enqueue. See
[Event Sourcing with ToriPy](tori-py.md) for synchronization callbacks and their
exact guarantees.
