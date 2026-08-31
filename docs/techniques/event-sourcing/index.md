# Event Sourcing

Event sourcing stores an aggregate's ordered domain events as its source of
truth. Current state is rebuilt by replaying committed events; new decisions
record more events and append them at an exact expected stream version.

Tori Py separates the framework-neutral model from the ToriPy integration:

| Need | Package | Guide |
| --- | --- | --- |
| Aggregates, stable schemas, store protocols, repository, and explicit Unit of Work | `tori-py-cqrs-event-sourcing-core` | [Aggregates and Schemas](aggregates-and-schemas.md), [Stores, Repositories, and Unit of Work](stores-repositories-uow.md) |
| ToriPy modules, repository injection, and automatic command transactions | `tori-py-cqrs-event-sourcing` | [Event Sourcing with ToriPy](tori-py.md) |

Install only the layer needed by the application:

```text
uv add tori-py-cqrs-event-sourcing-core
uv add tori-py-cqrs-event-sourcing
```

The ToriPy integration already depends on the framework-neutral package,
`tori-py-cqrs`, and `tori-py-cqrs-core`. All packages require Python 3.14.

## Core Vocabulary

The implementation keeps domain, serialization, storage, and transport records
distinct:

| Term | Meaning |
| --- | --- |
| Domain event | A concrete immutable `tori_py_cqrs_core.Event` describing a fact |
| Pending event | Domain event plus occurrence metadata, recorded but not committed |
| Encoded event | Stable alias, schema version, and opaque bytes |
| Append event | Encoded body plus complete occurrence metadata staged for storage |
| Stored event | Append event with committed stream version and global position |
| Recorded event | Decoded stored event used for aggregate replay |
| Stream | One aggregate history identified by `StreamId(category, key)` |
| Unit of Work | One transaction staging atomic appends to one or more streams |

Transport `Envelope`, `DeliveryMetadata`, and `DeliveryReceipt` are not event
storage records. A transport delivery ID identifies one delivery attempt; an
event metadata UUID identifies the persisted domain-event occurrence.

## Write and Replay Flow

A framework-neutral write normally follows this sequence:

```text
enter EventSourcingUnitOfWork
  -> create repository over that transaction
  -> load and replay an aggregate, or create a new aggregate
  -> execute synchronous domain behavior
  -> AggregateRoot.raise_event() applies and records domain facts
  -> repository.save() encodes and stages the complete pending snapshot
  -> unit_of_work.commit() validates and atomically commits all streams
  -> validate CommitResult
  -> advance aggregate versions and clear committed pending events
exit Unit of Work and transaction context
```

The aggregate's `version` is the last confirmed committed stream version. Raising
new events does not increment it. Pending events clear only after a validated,
confirmed commit.

Replay follows the inverse representation path:

```text
repository transaction read
  -> finite pages of StoredEvent
  -> schema alias lookup
  -> contiguous bytes upcasters
  -> current decoder
  -> RecordedEvent
  -> aggregate._apply() without recording new events
```

See [Aggregates and Schemas](aggregates-and-schemas.md) for domain and evolution
rules, then [Stores, Repositories, and Unit of Work](stores-repositories-uow.md)
for transaction and outcome behavior.

## Stream and Ordering Rules

- A missing stream has version `0`.
- The first committed event has stream version `1`.
- Stream versions are positive and contiguous.
- Every append supplies an exact `expected_version`.
- Appending `N` events at version `V` assigns versions `V + 1` through `V + N`.
- One transaction accepts at most one append batch per stream.
- The reference store assigns positive contiguous global positions in
  transaction staging order and event order within each batch.
- Deletion is a domain event, not physical stream removal.
- The repository path has no "any version" append mode.

`StreamId.category` and the encoded aggregate key are stable application
contracts. They are not derived from a Python module or class path. The ID
encoder must be deterministic and collision-free within the category and tenant
namespace.

## Stable Schema Identity

Persisted event identity is an explicit alias such as
`community.member-registered`, not CQRS core's fully qualified Python routing
name. An event schema binds that alias to a current event class, positive schema
version, bytes encoder/decoder, and every required one-version upcaster.

The schema registry is configure-then-freeze. Persistence use before `freeze()`
fails, as does registration after freeze. This makes the set of accepted
persisted aliases explicit for one application graph and avoids package scans,
dynamic imports, or a mutable process-global registry.

## Optimistic Concurrency

Repositories save at `expected_version=aggregate.version`. The store checks that
version against current committed state only when the transaction commits. Two
transactions can therefore load the same version, but only the first compatible
writer wins; the other receives `OptimisticConcurrencyError` with structured
`stream_id`, `expected_version`, and `actual_version` attributes.

A conflicting Unit of Work is a confirmed non-commit, but every aggregate
enlisted in it is faulted because its decisions were made from a stale snapshot.
Discard those instances and reload before deciding again. Do not append their
retained pending events blindly.

## Commit Certainty

The Unit of Work exposes one immutable final classification:

| Outcome | Meaning | Required response |
| --- | --- | --- |
| `ConfirmedCommit` | Storage returned and the Unit of Work validated a complete `CommitResult` | Continue; aggregates are advanced |
| `ConfirmedNonCommit` | Storage is known not to have committed | Compensation or a newly decided retry may be possible |
| `IndeterminateCommit` | The durable result cannot be proved | Reconcile from storage; do not blindly retry |

Connection loss or cancellation can happen after a durable database committed
but before acknowledgement reached the process. A production store adapter must
raise `IndeterminateCommitError` for that ambiguity. Raw `CancelledError` from a
store's `commit()` is reserved for a confirmed non-commit. Unknown failures after
commit begins and malformed commit results are treated as indeterminate by the
Unit of Work.

The in-memory reference store has no remote acknowledgement boundary, so
cancellation while it waits for its commit lock has a known non-commit outcome.

## Persistence Is Not Publication

The event-sourcing packages do not publish persisted events through
`EventBus`:

- `AggregateRoot.raise_event()` records only aggregate pending state;
- `EventSourcingUnitOfWork.commit()` persists only through `EventStore`;
- `CommitResult` is not sent to a transport;
- `DeliveryReceipt` is never persistence proof;
- projections can consume bounded `EventStore.read_all()` pages, but checkpoint
  storage and runners are not included.

Publishing directly inside a command occurs before the event-store commit and
creates a dual-write failure window. A ToriPy `after_commit` callback can enqueue
an in-process notification after confirmed commit, but process loss can still
lose that notification.

Reliable production publication requires event rows and outbox rows written in
the same database transaction, followed by a separate relay. Projectors require
durable checkpoints and idempotency by persisted event ID. These are adapter and
application boundaries, not hidden framework behavior.

## In-Memory Reference Scope

`InMemoryEventStore` proves protocol semantics and supports tests. It provides
repeatable transaction snapshots, atomic multi-stream commit, expected-version
validation, duplicate event-ID checks, bounded reads, and deterministic global
order.

It is process-local and not durable. It has no migrations, database isolation
profile, outbox, retries, projection runner, snapshots, backup, or failover.

## When to Use the Technique

Event sourcing is useful when the ordered decision history is itself valuable,
domain behavior naturally belongs in aggregate boundaries, audit/evolution
requirements justify explicit schemas, and the team can operate projection and
schema-evolution workflows.

Do not choose it merely to obtain an event bus or CRUD audit log. It adds
expected-version conflicts, replay compatibility, immutable-data policy,
projection lag, ambiguous-commit reconciliation, and operational tooling
requirements. Standard persistence plus explicit domain events or an outbox is
often the smaller correct design.

## Guide Map

- [Aggregates and Schemas](aggregates-and-schemas.md) covers recording, replay,
  faulting, metadata, aliases, codecs, upcasters, and resource limits.
- [Stores, Repositories, and Unit of Work](stores-repositories-uow.md) covers
  transaction snapshots, loading, staging, optimistic concurrency, atomic
  commit, outcomes, and indeterminate commits.
- [Event Sourcing with ToriPy](tori-py.md) covers keyed roots/features,
  repository injection, transactional command decorators, synchronization,
  scopes, finalization failures, and the outbox boundary.
