# Persistent Streams Architecture

Status: implemented. Executable requirements are split into
`spec/tori-py-persistent-streams-core/phase-ps0-*.md` through `phase-ps4-*.md`.

## 1. Purpose

`tori-py-persistent-streams-core` is a framework-neutral abstraction for an append-only,
partitioned persistent log. Producers append opaque records to named logical
streams. Independent consumer groups process each partition in offset order and
checkpoint progress after successful processing.

The first slice establishes portable semantics, an in-memory reference
implementation, and a reusable conformance suite. It deliberately does not
provide durable storage or a production broker adapter.

This package is not an event store for aggregates, a CQRS bus, or a task queue.
It can carry encoded domain events, integration events, audit records, or other
application-defined bytes without knowing their schema or meaning.

## 2. Goals

The first slice MUST provide:

- one standalone `tori-py-persistent-streams-core` distribution;
- a Python 3.14 import package named `tori_py_persistent_streams_core`;
- opaque byte payloads and immutable application headers;
- mandatory UUID record identity;
- named logical streams partitioned by a configured deterministic router;
- monotonically increasing integer offsets and total ordering within each
  partition only;
- consumer groups with no more than one active owner for a partition;
- at-least-once processing with checkpoint-after-success behavior;
- broker-managed and external resume-cursor strategies;
- explicit poison-record behavior that stops the affected partition;
- optional named producers with monotonically increasing publishing IDs;
- beginning, end, exact-offset, timestamp, and relative-time start modes;
- explicit typed retention-gap failure;
- an in-memory semantic reference and reusable adapter conformance suite;
- finite limits and bounded reads throughout the public API.

## 3. Non-Goals

The first slice MUST NOT provide:

- a durable or production-ready storage implementation;
- CQRS commands, queries, event dispatch, aggregates, or event sourcing;
- ToriPy modules, dependency injection, controllers, or lifecycle integration;
- RabbitMQ, Kafka, Redis, PostgreSQL, SQLAlchemy, or another infrastructure
  adapter;
- Pydantic, msgspec, JSON, schema registration, serialization, or upcasting;
- global ordering across partitions or streams;
- cross-partition atomic append;
- exactly-once processing or atomicity with arbitrary handler side effects;
- automatic retries, backoff, dead-lettering, poison-record skipping, or
  checkpoint repair;
- stream joins, projections, materialized views, compaction, or transactions;
- stream deletion, partition-count changes, or retention-policy scheduling;
- a RabbitMQ stream `last_chunk` or equivalent end-of-stream shortcut;
- package scanning, global registries, or dynamic imports from record data.

## 4. Package Boundary

The first slice creates one distribution:

```text
distribution: tori-py-persistent-streams-core
import:       tori_py_persistent_streams_core
runtime:      Python standard library only
```

It has no dependency on `tori-py-cqrs-core`, `tori-py-cqrs-event-sourcing-core`, ToriPy, RabbitMQ,
SQLAlchemy, msgspec, or any application package. Those packages also gain
no reverse dependency during this slice.

The conformance API belongs to this distribution so future adapters can prove
the same public behavior. Test-runner integrations may be development-only; the
installed runtime facade MUST remain standard-library-only.

## 5. Vocabulary

- **Persistent log**: the configured collection of logical streams and their
  implementation-owned state.
- **Logical stream**: a stable, non-empty name and an immutable positive
  partition count.
- **Partition key**: opaque non-empty bytes used only to choose one partition.
- **Partition**: one append-only offset sequence within a logical stream.
- **Offset**: a non-negative integer position assigned by the log. Offset `0` is
  the first possible record in a partition.
- **Available bounds**: optional adapter observations describing the earliest
  and latest currently readable positions. They are cursors, not append proof.
- **Record**: an immutable identity, routing key, payload, headers, append time,
  partition, and offset.
- **Producer identity**: an optional stable name used to scope publishing IDs.
- **Publishing ID**: an optional non-negative, monotonically increasing integer
  used to make retries by a named producer idempotent.
- **Consumer group**: a stable non-empty name with independent progress for one
  logical stream.
- **Owner**: one active consumer instance holding fenced ownership of a
  partition for a group.
- **Resume cursor**: either an initialized inclusive start cursor before any
  record succeeds, or the offset of the last successfully processed record.
- **Start mode**: the rule used only when a partition has no checkpoint.
- **Poison record**: a record whose handler raises during the current delivery.
  The package does not infer that the record can never succeed.

## 6. Logical Streams and Routing

A logical stream is declared explicitly before use with:

- a non-empty stable stream name;
- a positive immutable partition count;
- finite configured limits for records, payloads, headers, names, and reads.

Redeclaring the same name with the exact same definition is harmless.
Redeclaring it with a different partition count or incompatible limits is a
typed configuration error. The first slice does not resize partitions.

Routing is provided by a deterministic `PartitionRouter` configured and
defensively copied as part of each stream definition. A custom router is an
immutable, pure value contract: its identity and routing configuration must be
stable and copyable, and `route` must depend only on its arguments and frozen
configuration. Its hashable `compatibility_key` fingerprints that configuration.
Adapters freeze the copied router identity and compatibility key at declaration.
Core supplies this default:

```text
partition = unsigned_big_endian(SHA-256(partition_key)) mod partition_count
```

The default router interprets the complete digest as one unsigned big-endian
integer. Empty
partition keys are invalid. Applications must use a stable byte encoding for a
business routing key. The partition key is retained on the stored record so
routing can be verified without understanding it. Other routers are allowed
when explicitly configured, stable, and supported by the adapter; changing a
stream's router or router version is a compatibility migration.

The contract promises ordering only for records routed to the same partition.
It makes no statement about the relative order of different partitions, even
when append calls occur sequentially in one task. There is no stream-wide or
log-wide position.

## 7. Record Model

An append request is immutable and contains:

- mandatory `record_id: UUID`;
- mandatory non-empty `partition_key: bytes`;
- mandatory opaque `payload: bytes`, which MAY be empty;
- immutable headers represented as non-empty string names to byte values;
- optional producer coordinates described in section 9.

A stored record adds:

- the logical stream name;
- the selected zero-based partition number;
- the assigned non-negative offset;
- a timezone-aware append timestamp assigned by the log.

The package copies byte-like input to `bytes` and headers to an immutable
representation at its boundary. It does not parse, normalize, compress,
encrypt, deserialize, or attach meaning to payloads or header values. Header
names are protocol metadata, not Python identifiers or import paths.

The caller assigns record UUIDs and is responsible for their practical
uniqueness. The first slice does not coordinate a log-wide uniqueness index,
which would introduce a cross-partition transaction. An unnamed producer can
therefore append separate occurrences carrying the same UUID; consumers use the
stream, partition, and offset as occurrence coordinates and apply `record_id`
idempotency according to application policy. A named-producer retry is the one
case that resolves to the same stored occurrence by contract.

Within a partition:

- accepted records receive unique, non-negative, strictly increasing offsets;
- gaps are allowed and no particular first assigned offset is promised;
- offset assignment and visibility are atomic for one record;
- records are returned in increasing offset order;
- append timestamps are timezone-aware and non-decreasing in offset order;
- previously returned records never mutate.

Appending one record is the first-slice atomic boundary. No API accepts a batch
that could imply atomicity across partitions.

## 8. Append and Read Semantics

The log API is asynchronous because durable adapters perform I/O. Append returns
a `PublishReceipt`, never a `StoredRecord`. The receipt contains `record_id`, the
selected partition, a typed outcome, and bounded adapter-neutral confirmation facts. It
does not contain a broker offset. Offsets and append timestamps are observed only
on consumed or read `StoredRecord` values. Available bounds and watermarks, where
an adapter supports them, are cursors and cannot reconstruct or prove an append.

Unknown acknowledgement outcomes are not made retry-safe by the base protocol.
The package performs no automatic retry. Exact retry after an indeterminate
outcome requires the caller to reuse both the same `record_id` and the same named
producer coordinates/handle.

Partition reads are finite and use an inclusive `from_offset` plus a positive
limit. They return retained records in increasing offset order and never cross a
partition. An empty result means only that no retained record is currently
available at or after the requested offset. It is not an end-of-stream signal.

Adapters explicitly advertise whether available bounds are observable. A
supported end cursor may bound a snapshot read, but it is not evidence that an
append occurred and need not equal the next assignable offset. The protocol has
no `last_chunk`, final-page flag, or broker-specific shortcut because a live
append-only stream has no permanent last chunk.

Reads from a cursor known to precede the earliest available position raise
`RetentionGapError`; they never clamp silently. An empty page may observe later
appends on a subsequent call.

## 9. Named Producers and Publishing IDs

Producer coordinates are optional as a pair:

- `producer_name`: a stable non-empty string;
- `publishing_id`: a non-negative integer.

Supplying only one coordinate is invalid. Routing selects the physical partition
before producer coordinates are validated. Publishing IDs are scoped by logical
stream, selected physical partition, and producer name. This is one physical
producer scope; there is no logical cross-partition sequence. For each scope:

1. A new accepted publishing ID MUST be greater than every previously accepted
   ID. Gaps are allowed.
2. Retrying the most recently accepted ID with an exactly equivalent append
   request returns a receipt for the same publication without appending again.
3. Reusing an accepted ID with different record identity, routing key, payload,
   or headers raises a typed publishing conflict.
4. An ID below the latest accepted ID raises a typed stale-publishing-ID error.
5. Producer state is independent of record retention and MUST NOT silently
   regress when old records are trimmed.

Equivalent retries do not promise exactly-once handler side effects. Unnamed
mode is fully supported without publishing-ID storage or producer exclusivity.
A mandatory UUID remains the stable record identity visible to consumers in
either mode.

## 10. Start Modes

A group subscription declares one start mode. It is consulted independently for
each partition only when that group has no checkpoint for the partition. An
existing checkpoint always wins.

- **Beginning**: start at the current earliest available cursor. This accepts
  that earlier retained history may no longer exist.
- **End**: start at the available end cursor captured when the uninitialized
  partition is first assigned. Records appended afterward are eligible.
- **Exact offset**: start at the supplied non-negative offset, inclusively.
- **Timestamp**: start at the first retained record whose append timestamp is
  greater than or equal to the supplied aware timestamp.
- **Relative time**: resolve an aware target timestamp as `clock.now() - age`
  when the uncheckpointed partition is assigned, then apply timestamp mode.

Timestamp ties are resolved by offset. A target after the latest retained record
resolves to the current end cursor. A target that could refer to removed
history raises `RetentionGapError` rather than silently starting at the low
watermark. Relative ages are finite, non-negative, and no greater than the
stream's `max_relative_age_days`. Resolution overflow against an aware clock is
a typed validation failure.

Adapters expose an immutable `StartModeCapabilities` value and advertise support
independently for each start mode. Acquisition rejects an unsupported start
before ownership or intake. Relative time
first resolves to a timestamp and then uses timestamp semantics. A timestamp
implementation must detect when retention or native clamping could hide matching
history; otherwise that mode is rejected before intake. It is never weakened to
beginning or end semantics.

The resolved inclusive start cursor is compare-and-created as an initialized
`ResumeCursor` before first delivery. It acknowledges no record and is distinct
from a cursor containing the last successfully processed offset. This makes end,
timestamp, and relative-time resolution stable across restart without `N + 1`
arithmetic. If another owner initialized progress concurrently, the stored
cursor wins. An adapter that cannot persist a required initialized cursor must
reject that start/strategy combination before intake. In particular,
broker-managed `END` on an empty stream is unsupported unless the adapter can
durably represent that exact empty-stream cursor without causing a later record
to be skipped.

## 11. Consumer Groups and Ownership

A subscription binds exactly one logical stream, consumer-group name,
checkpoint strategy, start mode, and owner identity. A group does not span
logical streams implicitly.

The first subscription that successfully initializes group progress fixes its
complete checkpoint strategy for that `(stream, group)` scope. An external
strategy includes a validated stable store identity as well as the store. The
portable contract freezes the stable identity; the in-memory process reference
also binds the exact store object and rejects another object with the same
identity because backend equivalence cannot be proven. Same-strategy
initializations reserve the pending choice so different partitions can initialize
concurrently. A failed or cancelled initialization releases its reservation and
does not prevent a later strategy choice. Later subscriptions using another
mode, external identity, or unproven store object fail configuration rather than
split progress across stores.
Changing strategy requires explicit application migration outside normal
consumption.

For each `(stream, group, partition)`:

- at most one owner is active at a time;
- ownership includes an opaque generation/fence token;
- only the current owner may fetch for processing or advance the checkpoint;
- one fetched record is reserved as the lease's sole in-flight delivery;
- a lease can checkpoint only that exact delivered object, and successful
  checkpoint, stop, or release clears the reservation;
- transfer requests revocation and waits for an in-flight handler to checkpoint,
  stop, or release before installing the new generation;
- transfer cancellation while waiting restores the old lease without creating
  overlapping ownership;
- stale fetch and checkpoint attempts fail with a typed ownership error;
- records are delivered serially in offset order within the partition;
- different owned partitions MAY be processed concurrently;
- losing ownership stops local processing before another record is invoked.

Assignments need not be balanced by a particular algorithm in the first slice.
The in-memory reference uses a deterministic assignment so tests are stable.
Conformance concerns exclusive ownership and fencing, not adapter-specific
rebalance optimization.

## 12. Resume-Cursor Strategies

After a record succeeds, the resume cursor stores that record's offset as the
last successfully processed position. On restart, consumption seeks strictly
after that exact offset. Before any record succeeds, the initialized cursor
stores an inclusive start position with a distinct tag. Cursor updates are
monotonic in observed record order; they never assume adjacency.

When no cursor exists, a strategy supports atomic compare-and-create of the
resolved initialized start cursor or rejects that start/strategy combination.

Two strategies are required:

Broker-managed checkpoints are supported only in explicitly configured
single-instance deployments. A shared external checkpoint store supports
multi-replica deployments only when every replica uses a replica-unique owner ID
and the store provides atomic fence replacement and exact-owner save validation.

### 12.1 Broker-managed checkpoints

The persistent-log implementation owns checkpoint storage. The processing runner
invokes the handler, awaits its successful return, then asks the log to persist
that record's offset as the last successfully processed position under the
current ownership token.

This does not make arbitrary handler side effects atomic with the checkpoint. A
failure after the side effect but before checkpoint confirmation can redeliver
the record.

### 12.2 External checkpoints

The application supplies `ExternalCheckpointStrategy(identity, store)` with a
stable, non-empty identity and an asynchronous checkpoint-store protocol keyed
by stream, group, and partition. The same handler-then-checkpoint ordering
applies. The group coordinator still owns and fences partition delivery; the
external store owns progress persistence.

An external checkpoint is explicitly not atomic with handler side effects or
with log ownership state. Implementations MUST NOT claim otherwise. Consumers
must make side effects idempotent by `record_id`, or use an application-owned
transactional inbox/checkpoint design outside this package when duplicate
effects are unacceptable.

External checkpoint writes reject regression and stale ownership. A checkpoint
write failure stops the partition because continuing could skip an uncheckpointed
record.

Ordinary definitive fence, load, compare-create, and save failures are translated to typed
checkpoint failures with the original cause. Persistence failures expose the
relevant attempted cursor when one is known; fence and pre-cursor load failures
use no cursor. Acquisition failures release ownership and strategy reservations,
and runtime load/save failures stop the affected lease before propagation.
Cancellation and process-control exceptions are never translated. Timeout,
cancellation, or disconnect while a store/query operation is in flight is
indeterminate: recovery may observe either the old or new cursor.

## 13. Delivery and Poison Records

Processing is at least once. For each partition, the runner performs exactly:

```text
load resume cursor or resolve and compare-create an initialized start cursor
  -> fetch next retained record
  -> await handler(record)
  -> persist last successfully processed record.offset
  -> fetch the next record
```

The runner never checkpoints before or concurrently with the handler. It never
advances past a failed record.

`next_record()` cannot be called again while a delivery is in flight. A direct,
fabricated, stale, or later record cannot be checkpointed through the lease.
Stopping or releasing abandons the in-flight delivery without advancing progress.

If a handler raises an ordinary exception:

- the record is not checkpointed;
- later records from that partition are not delivered;
- the partition enters a stopped state;
- a typed `PoisonRecordError` exposes stream, group, partition, offset,
  `record_id`, and the original cause;
- other partitions MAY continue unless the caller chooses to stop the complete
  subscription.

Restarting or explicitly reacquiring the partition redelivers the same record
from its unchanged checkpoint. There is no automatic retry loop, delay,
dead-letter stream, skip, or quarantine policy in the first slice.

Cancellation during the handler or checkpoint stops that partition and does not
advance progress. Cleanup attempts to release ownership. A durable adapter must
not turn an unknown checkpoint outcome into proof that progress did not advance;
redelivery remains valid under the at-least-once contract.

## 14. Retention and Gaps

Production adapters may remove old records according to adapter-owned retention
configuration. Core exposes watermarks and gap semantics but does not schedule
retention.

`RetentionGapError` is raised when a requested exact offset, timestamp-derived
position, or existing cursor precedes the earliest available record. It
contains at least:

- stream and partition;
- requested offset or timestamp;
- current available bounds when supported;
- group name when a group checkpoint caused the gap.

The package never auto-resets a stale checkpoint to beginning or end. Recovery
requires an explicit application decision and checkpoint administration outside
normal processing. Beginning mode is the only start mode that deliberately
selects the current retained beginning without reporting already-removed history.

The in-memory reference has no automatic time- or size-based retention. It
provides a controlled trim operation for tests and conformance, advances the
earliest available bound without renumbering offsets, retains the removed-time boundary
needed for start resolution, and never removes producer sequence or checkpoint
state.

## 15. Errors and Validation

The package defines one `PersistentStreamsError` base and typed failures for:

- invalid values and resource-limit breaches;
- unknown stream or incompatible stream declaration;
- invalid partition or offset;
- stale or conflicting publishing IDs;
- retention gaps;
- consumer ownership loss or stale fencing;
- invalid or regressing checkpoints;
- invalid subscription lifecycle;
- poison records;
- checkpoint persistence failures;
- adapter contract violations.

Value validation rejects booleans where integers are expected, naive
timestamps, mutable or malformed headers, empty required names/keys, out-of-range
partitions, non-finite durations, and oversized inputs before mutation.
Persisted and external checkpoint input is untrusted and receives the same
validation.

Control-flow failures such as `CancelledError`, `KeyboardInterrupt`, and
`SystemExit` are not converted to ordinary poison-record errors. Cleanup errors
must not erase the primary processing failure.

## 16. Resource Limits

Finite configurable limits cover at least:

- stream, group, owner, producer, and header-name lengths;
- partition count;
- payload and partition-key bytes;
- header count, individual value bytes, and aggregate header bytes;
- records returned by one read;
- relative start age in days;
- concurrently active owners and subscriptions in the in-memory reference.

Core supplies conservative defaults. Adapters MAY enforce stricter documented
limits but MUST pass conformance using values inside the common profile. There
are no unbounded public reads or implicit whole-stream materialization APIs.

## 17. Lifecycle Extension

`PersistentStreamAdapter` extends the complete `PersistentLog` protocol with
explicit `start()` and `quiesce()` barriers for application integrations that
own native intake. Core log conformance remains defined against `PersistentLog`;
the lifecycle extension does not make framework lifecycle a core concern.

`start()` returns only after native resources are ready for intake. `quiesce()`
closes native intake admission and crosses any callback handoff fence. Both are
adapter-neutral and can be implemented without a broker, as the in-memory
reference demonstrates.

## 18. In-Memory Reference

`InMemoryPersistentLog` is a semantic reference and test fixture. It MUST
provide:

- isolation between instances and no module-level mutable state;
- the core routing algorithm and immutable records;
- strictly increasing sparse offsets and non-decreasing append timestamps per partition;
- serialized state transitions under asynchronous concurrency;
- deterministic ownership assignment and generation fencing;
- broker-managed checkpoints;
- interoperability with the external checkpoint protocol;
- controlled partition trimming and exact watermark behavior;
- named-producer retry behavior independent of trimming;
- cancellation-safe ownership release and no fabricated durability;
- injectable clock/identity seams where deterministic tests require them.

It performs no disk writes, background retention, hidden retry, serialization,
or event publication. Process exit loses every record, checkpoint, producer
sequence, and ownership state.

## 19. Conformance Suite

The distribution ships reusable conformance cases against public protocols and
a factory for isolated adapter instances. A future adapter MUST run the common
suite in addition to infrastructure-specific tests.

The common profile verifies:

- stream declaration and incompatibility detection;
- deterministic partition-key routing;
- immutable opaque records and finite reads;
- per-partition strictly increasing offsets, permitted gaps, and ordering under concurrent append;
- explicit absence of cross-partition order guarantees;
- every start mode and checkpoint precedence;
- atomic start-checkpoint initialization and stable restart behavior;
- concurrent compare-create with one winning initialized cursor;
- exclusive ownership, fencing, transfer, and stale-owner rejection;
- checkpoint persistence translation, checkpoint-after-success, and no
  checkpoint on failure/cancellation;
- poison-record partition stop and redelivery after reacquisition;
- broker-managed and external checkpoint behavior;
- named-producer retry, conflict, stale ID, and retention independence;
- watermarks, controlled retention, and typed stale-checkpoint gaps;
- required lifecycle, validation, and resource-limit failures.

Portable cases are mandatory. Stale-retention cases use an explicit
administrative capability when available; adapter-specific durability,
clustering, and outage cases do not weaken the common profile.

Adapter-specific durability, clustering, rebalance timing, broker outages, and
unknown acknowledgement tests remain the adapter's responsibility.

## 19. Acceptance Flow

The first slice is accepted through one in-memory scenario:

1. Declare a logical stream with at least three partitions.
2. Append opaque records whose stable keys prove deterministic routing and
   within-partition ordering.
3. Retry one named-producer append and observe a receipt for the same accepted
   publication rather than a duplicate.
4. Start two owners in one group and prove each partition has one active owner.
5. Process records and checkpoint only after successful handlers.
6. Fail one handler, prove that partition stops, then reacquire and redeliver the
   same record while another partition can progress.
7. Repeat progress with an external checkpoint store and demonstrate the
   documented duplicate side-effect window.
8. Exercise beginning, end, exact-offset, timestamp, and relative-time starts.
9. Trim a partition, then prove a stale exact offset and stale checkpoint raise
   `RetentionGapError` without automatic reset.
10. Build wheel and source artifacts and run the scenario in an isolated `uv`
    environment with no other workspace package installed.

## 20. Public Module Layout

The initial package should remain small:

```text
tori_py_persistent_streams_core/
    __init__.py
    checkpoints.py
    consumers.py
    errors.py
    inmemory.py
    models.py
    protocols.py
    routing.py
    testing.py
    py.typed
```

`__init__.py` exports stable application-facing contracts. Conformance helpers
live under `testing`; in-memory administrative trim helpers need not be promoted
to the main facade.

## 21. Change Control

1. Update the owning PS phase file before changing an agreed behavior.
2. Update this architecture when package boundaries or semantic guarantees
   change.
3. Update `PERSISTENT_STREAMS_IMPLEMENTATION_PLAN.md` when phase order or scope
   changes.
4. Add or update conformance cases for every portable behavior change.
5. Do not resolve missing broker or persistence behavior silently in code.
