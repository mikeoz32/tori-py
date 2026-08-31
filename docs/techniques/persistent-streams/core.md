# Core Concepts

`tori-py-persistent-streams-core` is a standard-library-only Python 3.14 package.
It defines portable asynchronous contracts, an in-memory semantic reference, and
an adapter conformance helper. It does not provide durable storage.

```console
uv add tori-py-persistent-streams-core
```

## Define a Stream

A `StreamDefinition` fixes the logical name, positive partition count, limits,
and router:

```python
from tori_py_persistent_streams_core import StreamDefinition, StreamLimits

member_activity = StreamDefinition(
    "member-activity-v1",
    partition_count=8,
    limits=StreamLimits(
        max_payload_bytes=256 * 1024,
        max_read_records=250,
    ),
)
```

Declaration is explicit and idempotent only for the same compatibility contract.
Changing partition count, limits, router identity, or router configuration is an
incompatible redeclaration, not an in-place resize.

The default limits are:

| Limit | Default |
| --- | ---: |
| Stream, group, owner, and producer name | 128 characters each |
| Header name | 128 characters |
| Partitions | 1,024 |
| Payload | 1,048,576 bytes |
| Partition key | 4,096 bytes |
| Headers | 64 |
| One header value | 16,384 bytes |
| Aggregate encoded header names and values | 65,536 bytes |
| Records in one read | 1,000 |
| Relative start age | 365,000 days |

Adapters may document stricter limits. Validate the complete deployed stack, not
only the core model.

## Route Records

The default `Sha256PartitionRouter` uses the complete SHA-256 digest:

```text
partition = unsigned_big_endian(SHA-256(partition_key)) % partition_count
```

Use one stable byte encoding for a business key. Records for the same bytes route
to the same partition while the partition count and router remain unchanged.
Changing key encoding, partition count, router identity, or router configuration
is a data migration because old and new records may no longer share order.

A custom router implements the public value contract:

```python
from dataclasses import dataclass

from tori_py_persistent_streams_core import PartitionRouter, StreamDefinition


@dataclass(frozen=True, slots=True)
class PrefixRouter:
    identity: str = "prefix-v1"

    @property
    def compatibility_key(self) -> tuple[str]:
        return (self.identity,)

    def route(self, partition_key: bytes, partition_count: int) -> int:
        return partition_key[0] % partition_count


router: PartitionRouter = PrefixRouter()
definition = StreamDefinition("activity-v1", 4, router=router)
```

Routers must be deterministic, copyable, and immutable-value objects. A stream
definition defensively copies the router and snapshots its identity and hashable
compatibility key. A router result outside `0..partition_count - 1` is rejected
before append.

## Append Records

An append request contains caller-controlled record identity and opaque data:

```python
from uuid import uuid4

from tori_py_persistent_streams_core import AppendRequest

request = AppendRequest(
    record_id=uuid4(),
    partition_key=b"member-123",
    payload=b'{"display_name":"Ada"}',
    headers={"schema": b"member-updated-v1"},
)
receipt = await log.append("member-activity-v1", request)
```

The model copies byte-like inputs and exposes immutable headers. Payloads may be
empty; partition keys may not. Core does not interpret, compress, encrypt, or
deserialize application data.

`PublishReceipt` contains:

- `record_id`, the caller's UUID.
- `partition`, selected by the frozen router.
- `outcome`, a `PublishOutcome` value.
- Bounded adapter-neutral `confirmation_facts`.

It deliberately contains no append offset or stored record. A confirm means only
the adapter's documented acceptance facts, never consumer execution, exactly-once
effects, or a per-message fsync.

### Named Producers

Producer coordinates are optional and must be supplied together:

```python
request = AppendRequest(
    record_id=record_id,
    partition_key=b"member-123",
    payload=payload,
    producer_name="member-writer-v1",
    publishing_id=42,
)
```

The publishing ID is scoped by logical stream, selected physical partition, and
producer name. Within that coordinate:

- A newly accepted ID must be greater than every previously accepted ID; gaps are
  allowed.
- Retrying the latest ID with the exactly equivalent request can return
  `PublishOutcome.DEDUPLICATED`.
- Reusing an accepted ID with different content raises
  `PublishingConflictError`.
- An ID below the latest accepted ID raises `StalePublishingIdError`.
- Producer sequence state is independent of record retention.

Named publication can make a precisely identified retry idempotent at the append
boundary. It does not make consumer effects exactly once. Unnamed publication is
a complete supported mode and stores no publishing-ID state.

## Read Records

Reads are finite, inclusive by offset, partition-local, and offset ordered:

```python
page = await log.read(
    "member-activity-v1",
    partition=3,
    from_offset=120,
    limit=100,
)

for record in page.records:
    print(record.offset, record.record_id, record.payload)
```

Offsets are non-negative and strictly increasing within a partition, but may
contain gaps. There is no order across partitions and no stream-wide position.

`RecordPage.bounds` is optional because not every adapter can expose trustworthy
available bounds. Where present, `AvailableBounds` contains read cursors, not
append evidence. An empty page says only that no retained record is currently
available at or after the requested offset. It is not a permanent end marker.

## Choose a Start

A `Subscription` specifies a start for a previously uninitialized group
partition:

| Start value | Meaning |
| --- | --- |
| `Beginning()` | Current retained beginning; deliberately accepts older retention loss |
| `End()` | End captured during first initialization; later records are eligible |
| `ExactOffset(n)` | Offset `n`, inclusively |
| `Timestamp(when)` | First retained record at or after an aware timestamp |
| `RelativeTime(age)` | Resolve `now - age`, then use timestamp semantics |

```python
from datetime import UTC, datetime, timedelta

from tori_py_persistent_streams_core import (
    Beginning,
    End,
    ExactOffset,
    RelativeTime,
    Timestamp,
)

starts = (
    Beginning(),
    End(),
    ExactOffset(120),
    Timestamp(datetime(2026, 1, 1, tzinfo=UTC)),
    RelativeTime(timedelta(hours=24)),
)
```

Each log exposes `start_mode_capabilities`. Check it when code is intended to run
against different adapters:

```python
if not log.start_mode_capabilities.supports(configured_start):
    raise RuntimeError("the deployed adapter does not support this start")
```

Unsupported starts fail before ownership or intake. Existing progress always
overrides configuration, including a later change to `Beginning()` or `End()`.
The newly resolved start is persisted as a distinct initialized cursor before
delivery, so end and time-based starts do not drift across restart.

Timestamp values must be timezone-aware. Relative ages must be finite,
non-negative, and within `StreamLimits.max_relative_age_days`. A target after the
latest retained record resolves to the current end. A target that could refer to
removed history raises `RetentionGapError` rather than clamping.

## Acquire a Lease

A consumer group owns independent progress per physical partition. A
`PartitionLease` represents one fenced owner of one
`(stream, group, partition)` coordinate:

```python
from tori_py_persistent_streams_core import (
    Beginning,
    CheckpointStrategy,
    Subscription,
)

lease = await log.acquire(
    Subscription(
        stream="member-activity-v1",
        group="member-search-v1",
        owner_id="projection-replica-a",
        start=Beginning(),
    ),
    partition=3,
    strategy=CheckpointStrategy.BROKER_MANAGED,
)
```

A lease has at most one in-flight record. `next_record()` cannot fetch another
until the exact delivered object is checkpointed, stopped, or released. A
fabricated, stale, or later record cannot be checkpointed.

Ownership carries an `OwnershipToken(owner_id, generation)`. A stale owner cannot
fetch or checkpoint. A forced local transfer requests revocation and waits for an
in-flight delivery to checkpoint, stop, or release before the replacement owner
can process. This prevents overlapping handlers for the old and new generation.

`next_record()` returning `None` means no record is currently available. Polling,
delay, and lifecycle policy belong to the caller or framework integration.

## Use ConsumerRunner

`ConsumerRunner` performs a finite serial pull and checkpoints each record only
after the handler succeeds:

```python
from tori_py_persistent_streams_core import ConsumerRunner, StoredRecord


async def project(record: StoredRecord) -> None:
    await projection_store.apply_once(record.record_id, record.payload)


try:
    processed = await ConsumerRunner().run_once(lease, project, limit=100)
finally:
    await lease.release()
```

The return value is the number of records processed in that pull. The runner does
not create an infinite polling loop and does not release the lease after normal
completion; ownership lifetime remains explicit.

If the handler raises an ordinary exception, the runner:

- Does not checkpoint the record.
- Stops that lease and does not fetch a later record from the partition.
- Raises `PoisonRecordError` with stream, group, partition, offset, record UUID,
  and the original cause.
- Leaves other partitions free to progress.

The core package does not retry, delay, dead-letter, quarantine, or skip the
record. Reacquisition starts from unchanged progress and redelivers it.

Checkpoint failures stop the lease. External persistence failures are exposed as
`CheckpointPersistenceError` with the original cause and the attempted cursor
when known. Cancellation and process-control exceptions are preserved rather
than converted into poison errors.

## Understand At-Least-Once

The safe order is effect, then checkpoint. It creates an unavoidable duplicate
window for arbitrary effects:

```text
handler effect commits
-> process or network fails
-> checkpoint is absent or uncertain
-> same record is delivered again
```

Use one of these application patterns:

- Make the effect idempotent by `record_id` or a stable domain operation ID.
- Store an inbox row and the effect in one application database transaction.
- Use a naturally idempotent replacement operation rather than an increment.
- Reconcile an indeterminate external effect before intentionally retrying it.

Do not catch a poison failure and manually checkpoint it unless the application's
governed recovery policy has independently established that losing that record is
acceptable. Core provides no skip API.

## In-Memory Reference

`InMemoryPersistentLog` is useful for tests and examples:

```python
from tori_py_persistent_streams_core import InMemoryPersistentLog

log = InMemoryPersistentLog(max_active_leases=128)
await log.declare_stream(member_activity)
await log.start()
try:
    receipt = await log.append("member-activity-v1", request)
finally:
    await log.quiesce()
    await log.close()
```

It supports all five start modes, both checkpoint strategies, deterministic
sparse offsets, and controlled `trim()` for tests. It performs no disk I/O,
automatic retention, hidden retry, or background work. Every record, checkpoint,
producer sequence, and lease disappears with the process.

Run its focused suite through the repository workspace:

```console
uv run pytest packages/tori-py-persistent-streams-core/tests
```

For cursor fencing and gap recovery, continue with
[checkpoints and retention](checkpoints-and-retention.md).
