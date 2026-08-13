# CQRS Event Sourcing Implementation Plan

Status: ES0-ES6 complete; production persistence adapters are follow-up work.

The phase map and cross-phase invariants are recorded in
[`spec/tori-py-cqrs-event-sourcing-core/README.md`](spec/tori-py-cqrs-event-sourcing-core/README.md).
Detailed executable phase specifications must be added before implementation of
the corresponding phase. This plan does not change the guarantees or non-goals
of the completed first `tori-py-cqrs-core` slice.

## 1. Goal

Build a reusable, framework-agnostic event-sourcing package for Python 3.14. It
must provide the domain and persistence contracts needed to rebuild aggregate
state exclusively from an ordered event stream while preserving optimistic
concurrency and explicit transaction boundaries.

The first acceptance flow is an in-memory profile aggregate:

1. Load a profile stream through an event-sourced repository.
2. Replay committed events without recording or publishing new events.
3. Execute synchronous domain behavior on the aggregate.
4. Record one or more pending domain events.
5. Commit the pending events atomically at the expected stream version.
6. Clear only the events included in a successful commit.
7. Rebuild an equivalent aggregate from the committed stream.
8. Read committed events in global-position order for a future projector.

The reference package proves these semantics in memory. It does not claim
durability. Production persistence, outbox delivery, and projection checkpoints
require later adapter packages and their own executable specifications.

## 2. Package Boundary

Create one optional distribution:

- distribution: `tori-py-cqrs-event-sourcing-core`;
- import package: `tori_py_cqrs_event_sourcing_core`;
- runtime dependency: `tori-py-cqrs-core` only;
- implementation runtime dependencies: Python standard library only.

The dependency graph is:

```text
tori-py-cqrs-event-sourcing-core -> tori-py-cqrs-core
tori-py-cqrs          -> tori_py, tori-py-cqrs-core
tori-py-cqrs-fastapi         -> FastAPI, tori-py-cqrs-core
```

There is no reverse import from `tori-py-cqrs-core`, `tori_py`, or `tori-py-cqrs` into the
event-sourcing package. `AggregateRoot` and `EventStore` do not belong in
`tori-py-cqrs-core`: CQRS can be used without event sourcing, and the existing bus and
transport contracts must remain persistence-agnostic.

The package must not depend on ToriPy, FastAPI, Pydantic, msgspec, SQLAlchemy,
PostgreSQL, Citus, Redis, RabbitMQ, or a DI framework.

## 3. Core Vocabulary

The implementation uses these distinct concepts:

- **Domain event**: an immutable `tori_py_cqrs_core.Event` describing a domain fact.
- **Pending event**: a domain event and immutable occurrence metadata recorded
  by an aggregate but not yet committed.
- **Encoded event**: a stable event type, schema version, and opaque byte payload
  produced by a schema codec.
- **Append event**: immutable occurrence metadata combined with an encoded event
  body and ready for persistence.
- **Stored event**: an append event assigned to a stream version and global
  position by an EventStore.
- **Recorded event**: a decoded domain event plus its persisted stream and
  occurrence metadata, used for aggregate replay.
- **Stream**: one ordered history identified by a stable `StreamId`.
- **Stream version**: the number of events committed to one stream.
- **Global position**: a monotonically increasing position in the store-wide
  committed event sequence.
- **Unit of Work**: one explicit transaction that stages and atomically commits
  changes to one or more streams.

Transport `Envelope`, `DeliveryMetadata`, and `DeliveryReceipt` are not storage
records. Transport delivery attempts may change while persisted event identity
must remain stable.

## 4. Stream Identity and Versioning

`StreamId` is an immutable value object with two non-empty strings:

- `category`: a stable domain name such as `profile`;
- `key`: the aggregate identifier encoded by application policy.

It must not derive `category` from a Python module or class path. Adapters store
the two components without relying on an ambiguous concatenated representation.

Version rules are fixed:

- a missing stream has version `0`;
- the first committed event has stream version `1`;
- stream versions are positive, contiguous integers;
- global positions are positive, unique, monotonically increasing integers;
- appending `N` events at expected version `V` produces versions `V + 1`
  through `V + N`;
- an existing stream can never be empty;
- deletion is represented by a domain event, not physical stream removal;
- there is no `ANY_VERSION` append mode in the public repository path.

The reference store supplies one total global order. A future distributed store
may define partitions, but it must do so in a separate specification rather than
weakening this contract silently.

## 5. Event Occurrence Model

`PendingEvent` is immutable and contains:

- one concrete `tori_py_cqrs_core.Event`;
- an event `UUID` assigned once when the aggregate records the event;
- a timezone-aware occurrence timestamp;
- optional correlation and causation UUIDs;
- immutable string-to-string headers.

Event identity and occurrence time remain unchanged across serialization and
commit retries. Technical delivery attempt information is not part of a pending
event.

Concrete domain event objects are required to be effectively immutable after
construction. The package does not deep-copy arbitrary user objects and cannot
make a mutable `Event` subclass safe. The documented default remains
`@dataclass(frozen=True, slots=True)`, and mutating an event after recording it is
an application contract violation.

`AppendEvent` contains the pending event's event ID, occurrence timestamp,
correlation and causation IDs, and headers together with the encoded event type,
schema version, and payload bytes. It is the complete input to EventStore append;
serialization must not discard occurrence metadata.

`StoredEvent` contains the persisted form:

- event ID;
- stream ID and stream version;
- global position;
- stable event type alias;
- positive schema version;
- timezone-aware occurrence timestamp;
- optional correlation and causation IDs;
- immutable headers;
- opaque payload bytes.

`RecordedEvent` contains the same identity, ordering, and occurrence metadata,
but carries the decoded domain event instead of payload bytes.

`CommitResult` is immutable and contains the committed `StoredEvent` values in
transaction staging order. It therefore provides every assigned stream version,
global position, and final stream version needed for Unit of Work validation and
later publication handoff.

Value objects validate UUIDs, aware timestamps, non-boolean integers, positive
versions and positions, concrete `Event` instances, immutable copied headers,
and byte payloads. Persisted input is untrusted and must fail with typed errors.

## 6. AggregateRoot Contract

`AggregateRoot[IdT]` is a mutable domain base class with synchronous behavior. It
owns:

- one application-defined aggregate ID;
- the last committed stream version;
- an ordered private collection of pending events.

Its public/protected behavior must support:

```python
class AggregateRoot[IdT]:
    @property
    def id(self) -> IdT: ...

    @property
    def version(self) -> int: ...

    @property
    def pending_events(self) -> tuple[PendingEvent, ...]: ...

    def raise_event(self, event: Event, *, metadata: EventMetadata | None = None) -> None: ...

    def _replay(self, events: Iterable[RecordedEvent]) -> None: ...

    def _prepare_commit(
        self,
        owner: object,
        events: Sequence[PendingEvent],
        *,
        version: int,
    ) -> object: ...

    def _mark_committed(self, prepared: object) -> None: ...

    def _apply(self, event: Event) -> None: ...
```

Required semantics:

1. `_apply()` is synchronous, deterministic, and side-effect-free outside the
   aggregate.
2. Domain methods validate decisions before calling `raise_event()`. `_apply()`
   is expected not to reject an event that is valid for the aggregate version.
3. `raise_event()` constructs and fully validates occurrence metadata before it
   applies the event, then records the successfully applied event as pending.
4. If `_apply()` raises, the base cannot prove whether partial mutation occurred.
   The aggregate always enters a faulted state and rejects replay, new events,
   staging, and commit; the caller must discard and reload it.
5. `_replay()` applies committed events without adding pending events and is an
   internal repository operation.
6. Replay starts on a pristine aggregate at version `0` and may continue in
   finite contiguous pages while the aggregate has no pending events and is not
   sealed or faulted.
7. Each replay page is structurally validated before its first event is applied.
   A malformed later page or application failure faults the aggregate; the
   repository discards it and never returns partially replayed state.
8. Saving enlists and seals the aggregate for exclusive ownership by one Unit of
   Work. A sealed aggregate rejects new events, replay, and another save until
   confirmed rollback or commit releases it.
9. `_prepare_commit()` binds an opaque transition token to the owning Unit of
   Work, exact pending snapshot, and final version before storage I/O.
   `_mark_committed()` accepts only that token and clears the exact snapshot only
   after confirmed storage commit.
10. Pending events remain present after serialization, definite append failure,
    rollback, or optimistic-concurrency failure. Conflict and duplicate-event
    outcomes also fault the stale aggregate, so retained events are diagnostic
    state rather than a reusable append batch.
11. An aggregate does not inject or call `EventBus`, EventStore, a repository,
    database session, or DI container. The base implementation's optional
    standard-library UUID/time defaults are limited to occurrence metadata.
12. Repository/UoW code invokes replay, validation, enlistment, preparation,
    commit, release, and fault through base-owned `AggregateRoot` methods so
    accidental subclass name collisions cannot override lifecycle transitions.
13. Aggregate event application uses an explicit `_apply()` implementation.
    Decorator discovery, async event appliers, and reflection-based dispatch are
    outside the first slice.

The base class may provide UUID and UTC timestamp defaults for `raise_event()`;
tests and applications can pass explicit immutable metadata when deterministic
identity is required.

## 7. Stable Event Schemas

Persisted event type identity is not `tori_py_cqrs_core.identity.message_type_for()`.
Python module and class names are routing implementation details and may change.

The package provides an explicit configure-then-freeze schema registry. Each
schema registration binds:

- one stable non-empty alias such as `profile.created`;
- one positive current schema version;
- one concrete `Event` subclass;
- an encoder from the concrete event to bytes;
- a decoder from current-version bytes to the concrete event;
- zero or more ordered one-version upcasters.

Registration is explicit. Decorators may attach direct schema metadata, but they
must not mutate a process-global registry or trigger package scanning.

The registry must reject:

- duplicate stable aliases;
- one event class registered under multiple aliases;
- duplicate or non-positive schema versions;
- missing upcast steps;
- upcast cycles or version regressions;
- decoded objects that do not match the registered concrete event class;
- unknown aliases or future schema versions.

Upcasters transform one persisted byte representation to the next schema
version. They do not execute aggregate behavior, access DI, perform I/O, or
publish events. Encoding the same immutable event under the same schema must be
deterministic.

No automatic dataclass, JSON, Pydantic, or msgspec serialization is required in
the first slice. Tests use explicit codecs so the storage contract remains
representation-neutral.

The package defines configurable finite resource limits for payload bytes,
header count and size, upcast steps, read page size, events per append batch,
events per transaction, and total encoded transaction bytes. ES2 freezes
the shared limits model and representation defaults; ES3 freezes and enforces
store, pagination, batch, and transaction limits. Codecs validate decoded shape
and complexity according to their own format; neither aliases nor payload bytes
are used for dynamic imports or code execution. Infrastructure adapters may
enforce stricter limits.

## 8. EventStore Protocol

`EventStore` is asynchronous because production implementations perform I/O. It
exposes bounded reads and an explicit transaction factory:

```python
class EventStore(Protocol):
    async def read_stream(
        self,
        stream_id: StreamId,
        *,
        after_version: int = 0,
        limit: int,
    ) -> tuple[StoredEvent, ...]: ...

    async def read_all(
        self,
        *,
        after_position: int = 0,
        limit: int,
    ) -> tuple[StoredEvent, ...]: ...

    def transaction(self) -> AbstractAsyncContextManager[EventStoreTransaction]: ...


class EventStoreTransaction(Protocol):
    async def read_stream(
        self,
        stream_id: StreamId,
        *,
        after_version: int = 0,
        limit: int,
    ) -> tuple[StoredEvent, ...]: ...

    def append(
        self,
        stream_id: StreamId,
        *,
        expected_version: int,
        events: Sequence[AppendEvent],
    ) -> None: ...

    async def commit(self) -> CommitResult: ...

    async def rollback(self) -> None: ...
```

`EventStoreTransaction` supports the same finite, version-paginated stream reads
needed by repositories, stages one or more append operations, and exposes
explicit `commit()` and `rollback()`. Leaving its context without a successful
commit rolls back staged work.

The minimum isolation contract is a repeatable committed snapshot established
when the transaction context is entered:

- repeated reads return the same committed data;
- transaction reads do not expose another transaction's later commits;
- staged appends are not included in reads before commit;
- expected versions are checked against current committed state at commit time;
- atomic multi-stream commit does not imply serializable predicate reads or
  protection from cross-stream write skew.

Cross-aggregate invariants should be modeled inside one aggregate stream. A
future database adapter may offer a stronger serializable profile, but it must
report serialization failures explicitly and pass the minimum contract tests.

Append receives:

- stream ID;
- exact expected version;
- a non-empty ordered sequence of complete `AppendEvent` values.

`StreamId.category` is the authoritative stable stream category. Append does not
accept a second category value that could disagree with the stream ID.

Commit guarantees:

1. All staged append batches commit atomically or none commit.
2. Each stream's expected version is checked against committed state.
3. Every event receives exactly one stream version and global position.
   Positions follow transaction staging order and event order within each batch.
4. Duplicate event IDs fail deterministically.
5. One transaction accepts at most one append batch for a stream. Every second
   append for that stream is rejected, even when it repeats the expected version;
   protocol users must combine the events into one ordered batch.
6. The actual store state contains either every staged append or none; partial
   batches are never visible.
7. Commit and rollback are terminal and idempotent only where explicitly safe;
   using a closed transaction otherwise raises a typed lifecycle error.
8. Readers observe committed events only.
9. `read_stream()` returns an empty tuple for a missing stream.
10. Stream and global reads require positive finite limits and return version or
    global-position order respectively.

Cancellation or connection loss can happen after a durable database commits but
before the caller receives confirmation. A durable adapter must translate this
case to `IndeterminateCommitError`; raw `CancelledError` is reserved for a
confirmed non-commit outcome. A process failure across that boundary likewise
requires reconciliation after execution resumes. The Unit of Work must not mark
aggregates committed after an indeterminate outcome; those aggregate instances
become unusable and must be discarded and reloaded before any retry. A retry must
not blindly append the same batch. The in-memory reference store has no remote
acknowledgement boundary and provides a known rollback outcome when cancellation
happens while waiting for commit admission.

The protocol does not promise exactly-once command handling. Application-level
command idempotency remains necessary because a caller can retry after an
ambiguous timeout. Event IDs and optimistic concurrency provide the primitives
for adapters to implement stronger idempotency contracts later.

## 9. Typed Failures

The package defines one `EventSourcingError` base and specific errors for:

- invalid event-sourcing values;
- invalid aggregate lifecycle or replay;
- unknown event schema;
- duplicate event schema registration;
- unsupported future schema version;
- incomplete or failed upcasting;
- stream not found at repository level;
- optimistic concurrency conflict;
- duplicate event identity;
- invalid transaction lifecycle;
- confirmed non-commit failure;
- indeterminate commit outcome;
- cleanup failure after a confirmed commit, carrying the `CommitResult`;
- aggregate already enlisted or faulted;
- aggregate type/stream mismatch;
- aggregate commit-state mismatch.

`OptimisticConcurrencyError` exposes the stream ID, expected version, and actual
version as structured attributes. It must not be converted into a generic
transport or handler error by this package.

An indeterminate commit error is distinct from optimistic concurrency and a
confirmed rollback. It tells callers to discard tracked aggregate state and
reconcile from the store rather than retrying the same in-memory operation.
Adapters raise `ConfirmedCommitError` only when they can prove storage did not
commit. Unknown exceptions are treated as indeterminate by the Unit of Work.

## 10. InMemoryEventStore

The package includes `InMemoryEventStore` as a reference implementation and test
fixture. It is not a durable adapter.

It must provide:

- isolation between store instances;
- serialized transaction commit through an async lock;
- atomic multi-stream validation before mutation;
- contiguous per-stream versions;
- one deterministic global committed order;
- immutable records returned to callers;
- bounded stream and global reads;
- rollback, known-outcome cancellation, and transaction snapshot safety;
- a synchronous `COMMITTING` transition before waiting for the commit lock so
  reads, append, rollback, and a second commit cannot race the active commit;
- the same typed concurrency and duplicate-ID failures required of production
  adapters.

No module-level mutable state, background worker, artificial retry, disk write,
or event publication is allowed.

The EventStore protocol receives reusable contract tests. Every future adapter
must run those tests in addition to its database-specific integration suite.

## 11. Repository and Unit of Work

`EventSourcedRepository[AggregateIdT, AggregateT]` composes:

- a stable stream category;
- an aggregate factory that creates a pristine aggregate for one ID;
- the exact aggregate implementation type accepted from the factory and save;
- a frozen event schema registry/codec;
- a positive repository page size no greater than shared schema limits;
- the current EventStore transaction.

Repository load behavior:

1. Derive `StreamId(category, encoded aggregate ID)` through an explicit ID
   encoder. The encoder must be stable, deterministic, and collision-free within
   its category and tenant namespace.
2. Read the complete committed stream inside the current repeatable transaction
   using finite, contiguous version pages.
3. Raise a typed not-found error when required load sees no stream.
4. Decode and upcast each stored event.
5. Validate stream identity and contiguous versions.
6. Replay the recorded events onto a pristine aggregate.

Repository save behavior:

1. Reject a wrong aggregate type, faulted aggregate, aggregate already enlisted
   by any Unit of Work, repeated save, or second aggregate instance targeting an
   enlisted stream before running an event encoder.
2. Capture an immutable snapshot of pending events.
3. Return without enlistment when there are no pending events.
4. Encode each event and combine its encoded body with the complete occurrence
   metadata to produce `AppendEvent` values.
5. Stage one append at `expected_version=aggregate.version`.
6. Register and seal the aggregate with the exact pending snapshot and stream.
7. Reject repeated save of the same aggregate in one Unit of Work rather than
   duplicating or coalescing append plans.
8. Do not clear pending events during staging.

`EventSourcingUnitOfWork` owns one EventStore transaction and tracked aggregate
commit plans. Before its first storage-commit await, `commit()` validates every
sealed aggregate, pending snapshot, stream, expected version, and final version
transition and synchronously enters `COMMITTING`. Competing stage, rollback,
commit, and transaction access are rejected until commit resolves. It then
commits all staged store writes, validates the returned `CommitResult`, and
performs a prevalidated, non-failing local transition that clears each exact
pending snapshot and advances its version. A malformed result is an adapter
contract violation and places the same aggregate instances into the indeterminate
state rather than reporting a confirmed rollback.

A typed confirmed non-commit failure, raw known-rollback cancellation, or
deliberate rollback releases aggregates while retaining their pending events.
Unknown exceptions are treated as indeterminate. Optimistic-concurrency and
duplicate-event conflicts prove the in-memory aggregate is stale or ambiguous;
because the Unit of Work is atomic, either conflict faults every enlisted
aggregate and requires discard/reload rather than releasing a partial set for
reuse. An indeterminate outcome likewise does not mark events committed and
faults all enlisted aggregate instances. Leaving the scope without attempting
commit rolls back and releases its aggregates. These rules prevent a successful
store commit from being reported as a normal local bookkeeping failure.

After confirmed commit, an adapter context cleanup failure is raised as
`ConfirmedCommitCleanupError` carrying the confirmed `CommitResult`. Callers must
not retry the command as if storage had rolled back.

The first slice supports atomic multi-stream writes through one Unit of Work,
but it does not implement cross-store or distributed transactions.

## 12. Publication and Projection Boundary

Persisting an event and publishing it through the existing `EventBus` are not one
atomic operation. This package must not hide that dual-write failure window.

The package therefore:

- never publishes from `AggregateRoot`;
- never treats `EventBus.publish()` or `DeliveryReceipt` as persistence proof;
- exposes committed events through stream/global reads;
- preserves event, correlation, and causation IDs needed by a future publisher;
- does not automatically publish after an in-memory commit.

A production persistence adapter must write event rows and transactional outbox
rows in the same database transaction. A separate relay may publish committed
events after commit. Every delivery attempt gets a new delivery ID while the
persisted event ID remains the logical message ID.

Durable projectors require their own persisted checkpoints and idempotency by
event ID. `read_all()` supplies the ordered feed, but checkpoint storage,
retries, poison-event policy, dead letters, and projection runners are outside
this package's first slice.

The existing `tori-py-cqrs-core.EventBus` remains suitable for non-durable, in-process
notifications. Metadata-preserving publication through that bus requires a
separate `tori-py-cqrs-core` specification rather than a private API dependency.

## 13. Implementation Phases

### ES0: Workspace and contracts

1. Add the executable ES0 specification before workspace changes.
2. Add the distribution to the `uv` workspace.
3. Freeze dependency direction and public module layout.
4. Add the executable ES1 specification before behavior code.
5. Add import-boundary and isolated artifact smoke tests.
6. Keep the package facade importable without optional infrastructure.

### ES1: Event records and AggregateRoot

1. Implement stream IDs, occurrence metadata, pending events, and recorded
   events.
2. Implement `AggregateRoot` recording, replay, and exact commit-state semantics.
3. Add faulted and exclusively enlisted aggregate lifecycle states.
4. Add validation and typed aggregate lifecycle errors.
5. Test replay purity, failed application, exact pending order, seal/release, and
   failed commit retention.

### ES2: Stable schemas, codecs, and upcasters

1. Implement explicit mutable-then-frozen schema registration.
2. Implement encoded, append, and stored event value objects.
3. Implement deterministic encode/decode and contiguous upcast chains.
4. Define finite payload, metadata, upcast, append-batch, transaction, and
   pagination resource-limit configuration; enforce representation limits here.
5. Reject duplicate, unknown, malformed, and future-version schemas.
6. Test renamed Python classes against unchanged stable event aliases.

### ES3: EventStore and reference implementation

1. Define EventStore and transaction protocols.
2. Implement typed concurrency, duplicate identity, and lifecycle failures.
3. Implement `InMemoryEventStore` with atomic multi-stream commit.
4. Enforce pagination, append-batch, transaction-event, and transaction-byte
   limits.
5. Add reusable EventStore contract tests.
6. Test repeatable transactional reads, duplicate-stream append rejection,
   concurrent writers, known-outcome cancellation, rollback,
   indeterminate-outcome adapter fakes, ordering, and finite pagination.

### ES4: Repository and Unit of Work

1. Implement aggregate factories and explicit ID encoders.
2. Implement repository load, replay, stage-save, and not-found behavior.
3. Implement explicit Unit of Work commit/rollback ownership.
4. Implement exclusive enlistment and prevalidated no-fail commit transitions.
5. Ensure aggregate pending events clear only after confirmed storage commit.
6. Add repeated-save, duplicate-stream-instance, multi-aggregate atomic commit,
   and conflict tests.

### ES5: Acceptance flow and hardening

1. Add the in-memory profile aggregate acceptance flow.
2. Rebuild equivalent state from the committed stream.
3. Demonstrate optimistic concurrency and global ordered reads.
4. Review all public exports, error attributes, protocol runtime behavior, and
   documentation.
5. Build wheel and source distributions and smoke-test both in isolated `uv`
   environments.
6. Run the full repository quality gates.

## 14. Public Module Layout

The initial package layout should remain small:

```text
tori_py_cqrs_event_sourcing_core/
    __init__.py
    aggregate.py
    codec.py
    errors.py
    events.py
    protocols.py
    repository.py
    store.py
    py.typed
```

`__init__.py` exports only stable application-facing types. Reference
implementation details stay in their owning modules unless a concrete type is
intended for application tests.

## 15. Verification Targets

All commands run through `uv`:

```text
uv run pytest packages/tori-py-cqrs-event-sourcing-core/tests
uv run ruff check .
uv run ruff format --check .
uv run ty check packages/tori-py-cqrs-event-sourcing-core/src packages/tori-py-cqrs-event-sourcing-core/tests
uv build --package tori-py-cqrs-event-sourcing-core
uv run pytest
```

Artifact verification must install wheel and source distributions in isolated
`uv` environments, import the public facade, commit and replay one aggregate,
and prove that no framework or database dependency is required.

## 16. Explicit Non-Goals

- No SQLAlchemy, PostgreSQL, Citus, migrations, or connection pooling.
- No durable claim for `InMemoryEventStore`.
- No transactional outbox table or relay worker.
- No RabbitMQ, Redis/Dragonfly, acknowledgements, retries, or dead letters.
- No automatic publication through `tori-py-cqrs-core.EventBus`.
- No durable projection runner or checkpoint database.
- No snapshots in the first slice; snapshots are a measured replay optimization,
  never the source of truth.
- No sagas, process managers, temporal queries, stream branching, or event
  deletion.
- No dynamic import from persisted event aliases.
- No automatic package scanning or process-global schema registry.
- No automatic dataclass/Pydantic/msgspec serialization.
- No command idempotency store or exactly-once command claim.
- No ToriPy/FastAPI integration module in this package.
- No Citus distribution design until global-order and uniqueness semantics have
  a separate specification.

## 17. Follow-Up Adapter Obligations

Before claiming production-ready event sourcing, later plans must define:

1. A PostgreSQL/SQLAlchemy adapter with real transaction isolation and migrations.
2. Atomic event-row and outbox-row persistence.
3. Adapter-specific ambiguous-commit detection, reconciliation, and command
   idempotency policy.
4. Metadata-preserving relay publication and retry semantics.
5. Durable projection checkpoints, idempotency, poison-event handling, and
   rebuild tooling.
6. Tenant isolation, authorization context, retention, backup, and audit policy.
7. Snapshot schema/versioning only after replay performance is measured.
8. Citus partitioning and ordering semantics if horizontal distribution becomes
   necessary.
