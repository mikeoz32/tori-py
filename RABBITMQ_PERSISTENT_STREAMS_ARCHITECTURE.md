# RabbitMQ Persistent Streams Architecture

## 1. Status

Status: RPS0-RPS7 incomplete after adversarial review. Focused real-broker tests
approve only the currently documented barrier, graceful SAC, producer-isolation,
quiesce, bounded-intake, and fail-closed behavior. Timestamp/relative starts,
external-store multi-replica fencing, transparent reconnect, exact public bounds,
cross-restart named-content association, TLS/fault gates, full Super Stream
movement, and release review remain unsupported or incomplete.

The proposed `persistent-streams-rabbitmq` adapter maps RabbitMQ native Streams
and Super Streams to core `PersistentLog` contracts and exposes a separate
Nestpy configured-adapter factory/runtime.

## 2. Package Boundary and Conformance

```text
persistent-streams-rabbitmq
  -> persistent-streams
  -> nestpy-persistent-streams
  -> nestpy
  -> rstream == 1.0.1
```

RabbitMQ objects have two explicit roles:

- `RabbitMqPersistentLog` implements the explicit adapter lifecycle contract.
  Portable `PersistentLog` conformance is not currently claimed because that
  suite assumes acquisition after implicit resource startup.
- `RabbitMqStreamAdapterFactory` and its managed runtime implement Nestpy
  composition, callback handoff, lifecycle, readiness, pipeline-completion, and
  shutdown contracts and run Nestpy adapter lifecycle/execution conformance.

Passing either suite does not imply passing the other. Native types remain
private except for a read-only typed `unwrap()`.

## 3. RPS0 Feasibility Gate

RPS0 must audit driver source and prove with a real broker, supported public APIs
or an explicitly pinned and isolated protocol compatibility bridge, and Python
3.14:

- regular Streams and fixed-partition Super Streams, metadata, routing, publish
  confirms, NACKs, timeout/disconnect ambiguity, and reconnect generations;
- named and unnamed producers, per-physical-producer publishing IDs, exact retry,
  and producer sequence queries;
- consumer-update start positions for beginning, end, exact offset, timestamp,
  and relative time after resolution to timestamp;
- broker timestamp behavior, native clamping, future timestamps, timestamp ties,
  and detection of retention gaps rather than silent clamp;
- broker-managed offset tracking, including the internal checkpoint records it
  creates, query/store ordering, retention effects, and disconnect uncertainty;
- durable representation and recovery of initialized `ResumeCursor` variants,
  including `END` on an empty stream, or explicit rejection of combinations the
  broker store cannot represent safely;
- retention of data and checkpoint records under age/byte/segment policies;
- SAC activation/promotion, credit, callback cancellation, Super Stream failover,
  automatic recovery behavior, and old-generation callback fencing;
- AMQP 1.0 message interoperability and access to broker/adapter append time on
  consumed records.

RPS0 does not need a publish offset: `PublishReceipt` deliberately has none.
Watermarks or available bounds are cursors, never evidence of an append. Each
start mode is capability-gated; failure of one mode rejects that mode rather than
silently weakening it or globally blocking independently proven modes.

### 3.1 RPS0 Result

RPS0 ran on CPython 3.14.6, `rstream==1.0.1`, and RabbitMQ 4.1.8 with
`rabbitmq_stream` and `rabbitmq_stream_management` enabled. The executable spike
is isolated under `packages/persistent-streams-rabbitmq/tests/feasibility`.

The public facade supports regular Stream create/existence/delete, Super Stream
create/delete, partition and binding-route lookup, named and unnamed publishing,
confirmed send with publishing ID but no offset, AMQP message encoding/decoding,
FIRST/LAST/NEXT/OFFSET/TIMESTAMP subscriptions, delivered offset and chunk
timestamp metadata, consumer offset query/store, SAC consumer updates, credit,
unsubscribe/close, recovery callbacks, and `ssl.SSLContext` inputs.

The narrow bridge resolves the former global blockers:

- `rstream.client.Client.query_publisher_sequence(stream, reference)` exists and
  returned publishing ID `43` through a dedicated authenticated metadata client.
- Stream protocol v1 command `0x1c` is absent from the driver's `Key` and schema,
  but the driver frame codec and `Client.sync_request()` support an adapter-owned
  request/response schema. Import-time audits freeze `rstream==1.0.1`, command
  values, method signatures, and schema registration so upgrades fail visibly.
- RabbitMQ 4.1.8 returned exactly `first_chunk_id`, `last_chunk_id`, and
  `committed_chunk_id`. Empty values were all `-1`; after an empty-stream
  initialized tracking value and one append they were `0`, `1`, and `1` in the
  spike. A byte-retained stream advanced `first_chunk_id` above zero, proving a
  lower watermark that detects an exact cursor lost to retention. RabbitMQ 4.1
  does not return the newer per-record `committed_offset` key.
- Broker tracking stores the complete tagged cursor as `(offset << 1) | kind`,
  where initialized is bit `0` and last-successful is bit `1`. Offsets are bounded
  to `0..2^63-1`; broker values span uint64. The adapter decodes first, subscribes
  inclusively at the original offset, and for a last-successful cursor discards
  delivered offsets `<=` it. This avoids `N + 1` and sparse-offset assumptions.
  Initialized empty `END` offset `0` round-tripped, and the first later data record
  at physical offset `1` was delivered.
- The canonical record is now a deterministic versioned binary envelope in one
  AMQP 1.0 binary body. Only `message-id` and `content-type` use flat standard
  properties; no nested application property is used.
- The Super Stream locator defect is contained by fresh public object/resource
  lifecycles for route, partition inspection, and deletion. No cache mutation,
  monkeypatch, or private driver state is used for this workaround.

Offset tracking records were not delivered but consume physical offsets, yielding
sparse data offsets; the RabbitMQ 4.1 queue detail response exposed no message
count for comparison.
FIRST, LAST, NEXT, exact OFFSET, and TIMESTAMP were functional; a beyond-tail
exact offset stayed parked rather than clamping to a later append. Messages in one
chunk shared a timestamp and a start at that timestamp included both; a future
timestamp natively clamped to NEXT and delivered the next append, with no public
fact exposing that clamp. Named retry of publishing ID 42 was deduplicated, SAC
promoted a standby after active unsubscribe, and a producer recovered after a real
broker application stop/start. The bundled AMQP decoder returned textual
properties as bytes, which requires strict adapter normalization. NACK induction,
disconnect-time offset-store certainty, checkpoint retention, full Super Stream
SAC failover, callback fencing, TLS certificate acceptance, and retention fault
hardening remain later gates. Chunk timestamps apply to a broker chunk and can tie
across records; StreamStats provides no retained timestamp watermark. Exact
per-record append-time timestamp and relative-time semantics remain unproven and
are explicitly unsupported by this adapter capability matrix.

## 4. Topology and Declaration

A regular logical stream maps to one RabbitMQ Stream. A partitioned logical
stream maps to one Super Stream and a fixed inspectable set of physical partition
streams and binding keys. Partition growth is a migration.

Declaration semantics are intentionally narrow:

- `CREATE`: idempotently create explicitly configured regular or Super Stream
  topology. Existing inspectable kind or partition topology conflicts fail.
- `REQUIRE_EXISTING`: create nothing; require inspectable topology to exist and
  fail inspectable kind or partition conflicts.

The adapter never claims runtime verification of settings the native public APIs
cannot inspect. Retention, segment size, replication, leader placement, broker
policy, and permissions are operator-owned preflight concerns unless a separately
approved management capability is added. Creation sends configured arguments,
but successful creation or existence is not proof of effective policy. The
adapter never deletes, recreates, truncates, or repairs topology.

## 5. Routing

The logical stream freezes a deterministic core `PartitionRouter` and version.
Core's SHA-256 router is the default. The Rabbit adapter must realize the selected
partition through the exact Super Stream binding key and prove vectors against a
real broker. It does not use `rstream`'s default MurmurHash, Python `hash()`, or
round robin unless a separately configured compatible router explicitly defines
that contract.

Changing router, key encoding, partition count, or binding mapping is a data
contract migration.

## 6. Canonical AMQP 1.0 Envelope

The following versioned envelope is frozen before any publication. Version 1 is
an AMQP 1.0 message with:

- `message-id`: canonical lowercase UUID text for `record_id`;
- `content-type`: required bounded ASCII media type for the encoded payload;
- body: one AMQP binary value containing the canonical record envelope;
- no subject, application properties, or nested AMQP values are required;
- binary prefix: ASCII magic `PSRM`, uint8 version `2`, uint8 kind, UUID bytes, uint32
  partition-key length, and uint16 header count;
- exact partition-key bytes;
- headers sorted by UTF-8 name bytes, each encoded as uint16 name length, name
  bytes, uint32 value length, and exact value bytes;
- uint64 payload length followed by exact payload bytes.

Limits independently bound total encoded message bytes, payload, partition key,
header count, header names, individual values, aggregate header bytes, content
type, and unknown fields. Malformed UUIDs, invalid UTF-8 names, non-canonical
order, trailing bytes, oversized values, and unsupported magic/version fail
decoding. Unknown transport properties are ignored, not copied into application
headers.

Application headers survive only inside the binary body. Transport metadata is a
separate fixed allowlist: message ID, content type, receive/chunk timestamp facts,
and native producer coordinates. Native annotations, delivery properties, and
broker metadata never overwrite or become application headers.

Kind `1` is an application record and kind `2` is an adapter barrier. Barriers
use the reserved `_psrm` key and cannot surface as `StoredRecord`.

## 7. Publishing and Deduplication

Publication encodes the frozen envelope, routes to a physical partition, admits
under finite pending-count/pending-byte limits, sends, awaits a confirm outcome,
and returns a `PublishReceipt` containing `record_id`, selected partition, typed
outcome, and bounded confirmation facts. It never returns a broker offset or
`StoredRecord`.

Each `(physical stream, producer name)` owns a distinct native producer; unnamed
publication has a separate per-physical-stream resource. Same-coordinate calls
are serialized. Publishing IDs are monotonic only within that coordinate.
In-memory request association detects retries and differing content. Broker
sequence alone cannot prove content equivalence after restart, so that case
returns `INDETERMINATE`, never `DEDUPLICATED`.

All core and Nestpy publication surfaces accept explicit `record_id`; configured
Nestpy publishers generate a UUID only when omitted. No accepted or indeterminate
publication is automatically retried. Exact retry after an indeterminate outcome
requires caller reuse of the same `record_id` and the same producer
coordinate/handle. If either is unavailable, outcome remains indeterminate.

Confirms prove only RabbitMQ's documented acceptance facts. Publishing IDs are
not offsets. Publication does not coordinate all writers, reserve record
positions, infer positions from available bounds, or verify append positions.

## 8. Starts, Consumption, and Retention

Core retains beginning, end, exact-offset, timestamp, and relative-time modes.
This adapter advertises beginning, end, and exact-offset. `END` confirms a unique
PSRM barrier, consumes through its observed offset, and initializes after that
control record. Finite reads use a barrier as their snapshot boundary and hide all
controls. Public `bounds()` returns `None`; chunk IDs are never record ends.
Timestamp and relative-time remain rejected.

For each supported mode the adapter must detect native clamp or retention loss
and raise a typed gap. If public APIs cannot distinguish an exact/timestamp cursor
from a clamp, that mode is rejected at startup. No mode is silently weakened.

SAC uses one identity per logical stream, group, and physical partition. Delivered
offsets must be non-negative and strictly increasing; gaps are valid. Processing
is serial per partition and finite credit follows framework capacity. Any envelope
decode, Nestpy pipeline, handler, work-scope cleanup, cursor persistence, or
ownership failure stops that partition and leaves its prior resume cursor
unchanged. Filters cannot convert failure to cursor eligibility.

## 9. Resume Cursors

Core `ResumeCursor` has two variants:

- initialized inclusive start cursor, persisted before first delivery;
- last successfully processed record offset, persisted after complete success.

Rabbit broker tracking stores the tagged uint64 representation described in
section 3.1, not a raw data offset. Both variants, including empty-stream `END`,
are supported within the 63-bit data-offset bound. Values outside that bound are
rejected before storage. Querying, decoding, and choosing the subscription/filter
behavior are adapter responsibilities.

Broker and external strategies are explicit and never substituted. Broker cursor
operations occur only in an active SAC generation.

Broker-managed checkpoints are supported only in explicitly configured
single-instance deployments. A shared external checkpoint store supports
multi-replica deployments only when every replica uses a replica-unique owner ID
and the store provides atomic fence replacement and exact-owner save validation.

A store, query, timeout, disconnect, mismatch, or retention uncertainty stops the
partition. Cursor persistence happens only after Nestpy reports complete pipeline
and work-scope cleanup success.

## 10. Lifecycle, Security, and Operations

Declaration and acquisition create no long-lived intake. `start()` subscribes and
waits for SAC activation. Demotion and quiesce close intake and wait for the
in-flight checkpoint before unsubscribe/handoff. `initial_credit` is fixed at one;
the pinned-driver stress test proves a finite adapter queue, current
`frame_max`-bounded frame, and at most one credited queued driver frame.

Automatic driver recovery is disabled because it replays cached subscriptions
outside adapter cursor fencing. Close callbacks increment the generation and fail
the adapter closed; recovery requires a new instance. Connections, callbacks,
confirms, queues, and shutdown are bounded and generation-fenced. Production requires verified TLS, redacted
credentials, finite operation deadlines, and a reachable stable endpoint or load
balancer. Old-generation callbacks cannot mutate replacement state. Intake opens
only after topology, capabilities, assignments, and cursors are prepared.

RabbitMQ confirms do not promise consumer execution, exactly-once effects, or
per-confirm fsync. SAC is not a transaction. Operations documentation owns
plugin, port, advertised-host, TLS/SASL, permissions, policy/retention preflight,
replica placement, disk/page cache, monitoring, and incident recovery.

## 11. Acceptance

If a revised architecture passes a new RPS0, release requires core and Nestpy conformance separately,
real-broker regular/Super Stream tests, canonical-envelope interoperability,
named and unnamed publishing, all advertised starts, sparse offsets, retention
gaps, SAC failover, cursor restart safety, reconnect fencing, TLS, bounded
backpressure/shutdown, Python 3.14 artifacts, and an explicit residual-risk
review. Any unproven required behavior keeps the adapter conditional.
