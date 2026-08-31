# Checkpoints and Retention

Checkpoints are the boundary between replayable delivery and application effects.
Their meaning, ownership, and failure classification must remain exact even when
offsets are sparse or old data has been removed.

## Resume Cursor Meaning

`ResumeCursor` has two tagged forms:

| Form | Meaning on resume |
| --- | --- |
| `ResumeCursor.initialized(offset)` | No record has succeeded; deliver the first retained record at or after `offset` |
| `ResumeCursor.last_successful(offset)` | Record `offset` succeeded; deliver the first retained record strictly after it |

```python
from tori_py_persistent_streams_core import ResumeCursor

initial = ResumeCursor.initialized(120)
progress = ResumeCursor.last_successful(120)

assert initial != progress
```

The tag prevents `offset + 1` arithmetic. Offsets may be sparse, and a broker can
insert control or tracking records between application records.

A new start is resolved and compare-and-created as an initialized cursor before
first delivery. If another owner initialized the same partition concurrently, the
stored winner takes precedence. Existing progress always overrides the configured
start.

## Broker-Managed Checkpoints

Select adapter-owned checkpoint storage explicitly:

```python
from tori_py_persistent_streams_core import CheckpointStrategy

strategy = CheckpointStrategy.BROKER_MANAGED
```

Broker-managed checkpoints are supported only for an explicitly declared
single-instance consumer-group deployment. This is a deployment constraint, not
merely an option value. Operators must ensure an old process and its replacement
cannot overlap, including after a disconnect or orchestrator timeout.

The checkpoint remains non-atomic with arbitrary handler effects. Broker storage
does not convert at-least-once delivery into exactly-once processing.

## External Checkpoints

An external strategy uses a stable store identity and a public `CheckpointStore`:

```python
from tori_py_persistent_streams_core import (
    ExternalCheckpointStrategy,
    InMemoryCheckpointStore,
)

strategy = ExternalCheckpointStrategy(
    identity="member-search-checkpoints-v1",
    store=InMemoryCheckpointStore(),
)
```

`InMemoryCheckpointStore` is process-local and intended for tests and examples.
A durable deployment supplies its own implementation of these asynchronous
operations:

```python
from typing import Protocol

from tori_py_persistent_streams_core import (
    CheckpointKey,
    OwnershipToken,
    ResumeCursor,
)


class DurableCheckpointStore(Protocol):
    async def fence(
        self,
        key: CheckpointKey,
        owner: OwnershipToken,
    ) -> None: ...

    async def load(self, key: CheckpointKey) -> ResumeCursor | None: ...

    async def compare_and_create(
        self,
        key: CheckpointKey,
        cursor: ResumeCursor,
        owner: OwnershipToken,
    ) -> ResumeCursor: ...

    async def save(
        self,
        key: CheckpointKey,
        expected: ResumeCursor,
        cursor: ResumeCursor,
        owner: OwnershipToken,
    ) -> None: ...
```

This example restates the public protocol shape; applications normally annotate
their implementation against `CheckpointStore` from the core facade.

## Fencing Requirements

For each `CheckpointKey(stream, group, partition)`, a shared external store must
provide all of these semantics:

- `fence` atomically replaces the current exact `OwnershipToken`.
- Every `compare_and_create` and `save` accepts only that exact current token.
- `compare_and_create` stores only an initialized cursor when no cursor exists and
  returns the one winning value under concurrent initialization.
- `save` performs compare-and-set against `expected` and rejects concurrent
  change, regression, stale ownership, or an invalid cursor kind.
- Cursor data and owner fencing survive every application replica that shares the
  consumer group.
- Timeouts and cancellation are treated as indeterminate unless the store can
  return a definitive result before control escapes.

An owner token combines the configured owner ID with an adapter generation. Every
replica must use a replica-unique owner ID. A shared hostname, deployment name, or
constant such as `"worker"` is not sufficient.

Tori Py requires an explicit deployment declaration when any binding uses an
external strategy:

```python
from tori_py_persistent_streams import PersistentStreamsRuntimeOptions

runtime = PersistentStreamsRuntimeOptions(
    owner_id="projection-replica-a",
    owner_id_is_replica_unique=True,
)
```

For a guaranteed single-instance deployment,
`single_instance_consumer_groups=True` can satisfy the integration's configuration
gate. It does not prove that the deployment is actually single instance.

One `(stream, group)` fixes its complete checkpoint strategy after successful
initialization. Changing broker versus external mode, external identity, or an
unproven store object is rejected. Migrate progress explicitly rather than
splitting a group across stores.

## Processing Boundary

For each record, progress advances only after all application work succeeds:

```text
decode
-> pipeline and handler
-> interceptor unwind
-> request/work-scope cleanup
-> checkpoint save and verification
```

External checkpoints are not atomic with handler side effects or broker
ownership. The duplicate window is expected:

```text
effect commits
-> checkpoint save fails, times out, is cancelled, or disconnects
-> recovery reads old or new cursor
-> record may execute again
```

Choose idempotency based on the effect:

| Effect | Typical protection |
| --- | --- |
| Database projection upsert | Store last record UUID or source version with the row |
| Increment or balance change | Transactional inbox plus unique record UUID |
| External API call | Idempotency key accepted by the remote system |
| Email or notification | Durable outbox with deduplicated send identity |
| Rebuilt projection | Drop and replay into a versioned replacement projection |

Do not assume a checkpoint failure means the cursor remained unchanged. A
definitive store rejection can establish failure; timeout, cancellation, or
disconnect while persistence is in flight is indeterminate.

`CheckpointPersistenceError` retains the original cause and the attempted cursor
when known. Runtime load and save failures stop the affected lease. The Tori Py
runtime marks cancellation during checkpoint as an unknown outcome and does not
guess that replay is certain.

## Ownership and Transfer

Only the current fenced owner may fetch or checkpoint. A lease reserves one exact
in-flight record. Transfer waits for that record to checkpoint, stop, or release
before a new generation can invoke a handler.

This prevents concurrent old/new owner execution inside one adapter, but it does
not make side effects transactional with ownership. A process can finish an
effect and lose ownership before progress is durably visible. Idempotency remains
required.

For shared stores, fencing must happen at the durable checkpoint store as well as
at the broker or adapter. Broker single-active-consumer status alone is not an
external-store transaction.

## Retention Gaps

Retention can remove records below a low watermark while a consumer is stopped.
Core raises `RetentionGapError` when an exact start, timestamp-derived start, read,
or existing checkpoint is known to precede retained history.

The error carries available facts:

- Logical stream and physical partition.
- Requested offset or timestamp.
- Available bounds when the adapter can expose them.
- Consumer group when an existing group checkpoint caused the gap.

The library never silently clamps a stale cursor to beginning or end. Silent
clamping would acknowledge data loss without an application decision.

`Beginning()` is intentionally different: for a previously uninitialized group,
it selects the current retained beginning and accepts that older history may no
longer exist. It does not repair an existing stale checkpoint.

## Retention Planning

Set retention from the recovery objective, not average lag:

```text
required retention
>= maximum planned outage
 + maximum incident detection time
 + maximum repair and redeploy time
 + replay catch-up time
 + safety margin
```

Also account for byte-based retention during traffic spikes. An age setting does
not protect a consumer if a byte cap removes history first.

Track a low-watermark margin per partition when the adapter exposes one:

```text
checkpoint distance from retained beginning
and
estimated time until retention reaches the checkpoint
```

Bounds are observations and can move immediately after they are read. They are
not append receipts or a transaction with checkpoint persistence.

## Recover a Gap

Stop all owners for the affected group before making a recovery decision. Then
choose one explicit policy:

1. Restore or replay the missing source history into a compatible replacement
   stream and rebuild the group from a valid coordinate.
2. Create a new versioned consumer group with `Beginning()` and record that older
   effects were intentionally abandoned.
3. Rebuild a disposable projection from another authoritative source, then start
   a new group at an explicitly selected retained point.
4. Administratively replace an external checkpoint with a governed initialized
   cursor only after fencing every old owner and documenting the lost range.

There is no normal consumption API for resetting or skipping a checkpoint. A new
group is usually safer because it preserves the old forensic state.

For RabbitMQ, broker tracking values are tagged cursors, not raw offsets. Never
edit them as an untagged integer. Prefer a new group or a purpose-built migration
that understands the adapter's encoding. See [RabbitMQ](rabbitmq.md).

## Recover a Poison Record

A poison record is an attempt whose decode, pipeline, handler, or cleanup failed.
It is not automatically proven permanently invalid.

1. Capture stream alias, physical stream, group, partition, offset, record UUID,
   diagnostic code, and deployment version without logging sensitive payloads.
2. Preserve the cursor and failing record. Do not advance to a later offset.
3. Deploy compatible codec or handler code, repair the downstream dependency, or
   apply a governed source-data migration.
4. Restart or replace the runtime so the unchanged checkpoint redelivers the
   record.
5. Verify idempotency for effects that may have completed during the first
   attempt.

Publishing a compensating record does not unblock the partition because the
poison record remains before it. If the organization elects to abandon the
record, use the same explicit checkpoint migration controls as a retention-gap
reset and retain an audit trail.

Operational runbooks continue in [operations](operations.md).
