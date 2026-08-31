# RabbitMQ Streams Adapter

`tori-py-persistent-streams-rabbitmq` maps logical streams to RabbitMQ native
Streams and fixed-partition Super Streams. Version `0.1.0` is a provisional,
conditional beta. Its package version is not an unconditional production-readiness
claim.

The adapter requires:

- CPython `>=3.14,<3.15`.
- RabbitMQ 4.1 with `rabbitmq_stream` enabled.
- Exactly `rstream==1.0.1`.
- `rabbitmq_stream_management` for the documented operator and feasibility
  preflight.

Focused broker evidence was executed against RabbitMQ 4.1.8. Later 4.1 patch
releases and different cluster/security layouts still require deployment
qualification.

```console
uv add tori-py-persistent-streams-rabbitmq
```

## Configure the Adapter

All application imports below use public facades:

```python
from tori_py_persistent_streams import PersistentStreamsModule
from tori_py_persistent_streams_rabbitmq import (
    DeclarationMode,
    RabbitMqConnectionOptions,
    RabbitMqPersistentStreamsModule,
    RabbitMqPersistentStreamsOptions,
)

rabbitmq = RabbitMqPersistentStreamsModule.for_root(
    RabbitMqPersistentStreamsOptions(
        connection=RabbitMqConnectionOptions(
            host="streams.internal",
            advertised_host="streams.example",
            username="member-service",
            password=secret_password,
        ),
        declaration=DeclarationMode.REQUIRE_EXISTING,
    )
)

streams = PersistentStreamsModule.for_root(
    application_stream_options,
    imports=[rabbitmq],
)
```

`REQUIRE_EXISTING` is appropriate when infrastructure automation owns topology.
`CREATE` idempotently creates missing configured topology and supplies retention
arguments, but does not verify that effective broker policy matches them.

Constructing connection options, adapter options, a deferred module, the factory,
or `RabbitMqPersistentLog` performs no network I/O. `for_root_async()` can resolve
options through normal annotation-driven Tori Py injection:

```python
rabbitmq = RabbitMqPersistentStreamsModule.for_root_async(
    use_factory=create_rabbitmq_options,
    imports=[secrets_module],
)
```

The options factory must return `RabbitMqPersistentStreamsOptions`.

## Connection Defaults

`RabbitMqConnectionOptions` has these exact defaults and validation bounds:

| Option | Default | Constraint |
| --- | ---: | --- |
| `port` | 5,552 | `1..65,535` |
| `vhost` | `/` | Non-empty |
| `heartbeat` | 60 | `1..2^31-1` |
| `frame_max` | 1,048,576 bytes | `1..2^31-1` |
| `load_balancer_mode` | `False` | Boolean |
| `advertised_host` | `None` | Non-empty when supplied |
| `sasl_mechanism` | `PLAIN` | `PLAIN` or `EXTERNAL` |
| `tls` | `None` | `RabbitMqTlsOptions` when enabled |
| `connection_name` | `tori-py-persistent-streams-core` | Non-empty |

The driver connects to `advertised_host` when supplied, otherwise `host`. Broker
advertised nodes must be reachable through that stable endpoint. Passwords are
excluded from dataclass representations, but must still come from a secret
provider rather than source control.

## Adapter Defaults

`RabbitMqPersistentStreamsOptions` uses these exact defaults:

| Option | Default | Meaning |
| --- | ---: | --- |
| `declaration` | `CREATE` | Create missing topology or require existing |
| `max_age_seconds` | 604,800 | Creation argument, 7 days |
| `max_length_bytes` | 1,073,741,824 | Creation argument, 1 GiB |
| `max_segment_size_bytes` | 100,000,000 | Creation argument; cannot exceed max length |
| `initial_credit` | 1 | Fixed to exactly one by the audited contract |
| `callback_queue_capacity` | 128 | Records buffered per partition lease |
| `max_pending_count` | 1,024 | Adapter-admitted publications |
| `max_pending_bytes` | 67,108,864 | Adapter-admitted estimated message bytes, 64 MiB |
| `max_streams` | 1,024 | Physical streams in this adapter's declared inventory |
| `max_named_producers` | 1,024 | Lifetime named producer coordinates/resources |
| `broker_managed_single_instance` | `False` | Explicit broker checkpoint safety gate |
| `confirm_timeout` | 10.0 seconds | Publish confirm deadline |
| `operation_timeout` | 10.0 seconds | Declaration, metadata, store, and query deadline |
| `close_timeout` | 10.0 seconds | Quiesce/resource close deadline |

Integer adapter limits are positive and at most `2^63-1`. Timeouts are positive
finite numbers. These are safety bounds, not sizing recommendations. Reduce or
raise them only after load testing the complete broker, network, and application
path.

`max_streams` counts physical partitions declared through one adapter instance.
A regular stream counts as one; an eight-partition Super Stream counts as eight.
It is not a broker-wide quota and does not inspect unrelated topology.

## Regular and Super Streams

The physical mapping is fixed:

| Logical definition | RabbitMQ topology | Physical names | Binding keys |
| --- | --- | --- | --- |
| `partition_count == 1` | Regular Stream | `<name>` | None |
| `partition_count > 1` | Super Stream | `<name>-0` through `<name>-(partition_count - 1)` | `"0"` through `"partition_count - 1"` |

For a Super Stream with three partitions, core routing returns `0`, `1`, or `2`,
and that integer maps exactly to binding key and physical suffix. The adapter does
not use `rstream`'s default hash. The configured core router remains authoritative.

Changing partition count, router, key encoding, physical suffix convention, or
binding keys is a data-contract migration. The adapter does not resize, delete,
truncate, recreate, or repair conflicting topology.

At startup it verifies only public inspectable facts:

- Regular versus Super Stream kind.
- Exact Super Stream physical partition names.
- Exact binding keys and one route per key.

`TopologyPreflight.unverified_facts` explicitly retains:

- Effective retention.
- Replication.
- Leader placement.
- Broker policy.
- Permissions.

Creation sends `max-age`, `max-length-bytes`, and
`stream-max-segment-size-bytes`. Successful creation is not proof of their
effective values or of replica placement.

## Supported Starts

The public capability value is exact:

```python
from tori_py_persistent_streams_rabbitmq import (
    RABBITMQ_START_MODE_CAPABILITIES,
)

assert RABBITMQ_START_MODE_CAPABILITIES.beginning
assert RABBITMQ_START_MODE_CAPABILITIES.end
assert RABBITMQ_START_MODE_CAPABILITIES.exact_offset
assert not RABBITMQ_START_MODE_CAPABILITIES.timestamp
assert not RABBITMQ_START_MODE_CAPABILITIES.relative_time
```

The adapter supports:

- `Beginning()`, resolved from the current StreamStats `first_chunk_id` low
  watermark.
- `ExactOffset(n)`, inclusively, after retention checks.
- `End()`, implemented with a confirmed PSRM barrier rather than native chunk
  metadata.

Timestamp and relative-time starts are rejected before subscription. RabbitMQ's
observed timestamps are chunk timestamps, and a future native timestamp start
clamps to next without an inspectable clamp fact. Those facts cannot implement
core's exact per-record timestamp and retention-gap semantics.

For `End()`, the active SAC owner publishes a unique barrier, observes its actual
delivered offset, persists that offset as an initialized cursor, then opens data
intake. The barrier is hidden from application handlers. This also makes empty
stream end safe: the first later data record is after the persisted barrier and is
eligible on the current run or restart.

## SAC Ownership

Each `(logical stream, group, physical partition)` uses one stable Single Active
Consumer identity:

```text
ps-<sha256(stream NUL group NUL partition)>
```

Leases are prepared before `adapter.start()`. Start opens native consumers and
registers SAC membership. Active ownership initializes or loads the cursor before
opening intake. Standby registration counts as adapter readiness, but its
`next_record()` waits until broker promotion.

Demotion closes intake and waits for the exact in-flight delivery to checkpoint
or be abandoned before deactivating the generation. Queued deliveries and
callbacks carry generations so stale work cannot mutate promoted state.

SAC is an ownership mechanism, not a transaction with handler effects or an
external checkpoint store.

## Tagged Checkpoints

RabbitMQ broker tracking stores a complete tagged cursor, not a raw data offset:

```text
encoded = (offset << 1) | kind_bit
kind_bit = 0 for initialized
kind_bit = 1 for last successful
```

Golden examples are:

| Cursor | Broker value |
| --- | ---: |
| initialized offset 0 | 0 |
| last-successful offset 0 | 1 |
| initialized offset 42 | 84 |
| last-successful offset 42 | 85 |

Data cursor offsets are limited to `0..2^63-1`; encoded broker values occupy
uint64 `0..2^64-1`. Tracking records consume physical offsets but are not
delivered as application records, so data offsets are expected to be sparse.

Broker-managed checkpoints require both an explicit adapter gate and a real
single-instance deployment:

```python
from tori_py_persistent_streams import PersistentStreamsRuntimeOptions
from tori_py_persistent_streams_rabbitmq import (
    RabbitMqPersistentStreamsOptions,
)

rabbit_options = RabbitMqPersistentStreamsOptions(
    connection,
    broker_managed_single_instance=True,
)

runtime_options = PersistentStreamsRuntimeOptions(
    owner_id="only-stream-process",
    single_instance_consumer_groups=True,
)
```

Both flags are declarations, not distributed locks. Operators must prevent old
and replacement processes from overlapping after shutdown, partition, or broker
disconnect.

Shared external checkpoints use core's `ExternalCheckpointStrategy`. The contract
requires replica-unique owner IDs plus a store with atomic owner replacement and
exact-owner compare-and-save. The adapter's full multi-replica external-store
fencing and cluster fault matrix remains a provisional release gate; validate the
chosen store and deployment rather than treating SAC alone as proof.

Checkpoint store/query timeout, cancellation, or disconnect is indeterminate.
The adapter stops the partition; recovery may observe either old or new cursor.

## Envelope

Application records use canonical PSRM v2:

- Content type
  `application/vnd.tori-py-persistent-streams-core.record.v2`.
- Binary magic `PSRM`, version `2`, and kind `1` for records or `2` for barriers.
- UUID bytes, partition-key length and bytes, canonical headers, and payload
  length and bytes.
- UTF-8 header names sorted by encoded bytes.
- Flat AMQP `message-id` and `content-type` only; application headers stay in the
  binary body.

The public standalone `EnvelopeLimits()` defaults are:

| Envelope limit | Default |
| --- | ---: |
| Total message | 2,097,152 bytes |
| Payload | 1,048,576 bytes |
| Partition key | 4,096 bytes |
| Header count | 64 |
| Header name | 256 encoded bytes |
| Header value | 16,384 bytes |
| Aggregate headers | 65,536 bytes |
| Content type | 128 ASCII bytes |

The adapter does not use the standalone total-message default unchanged. It
derives envelope limits from each `StreamDefinition.limits`:

```text
max envelope bytes
= max payload bytes
 + max aggregate header bytes
 + max partition-key bytes
 + 4,096 bytes framing allowance
```

Header-name bytes are bounded by four times the stream's character limit. The
serialized AMQP message must also fit `connection.frame_max`; the adapter uses
`len(serialized_message) + 64` for frame/admission accounting. With default
`frame_max`, a payload near core's 1 MiB maximum can therefore be rejected because
the envelope and AMQP overhead also need space. Size the stream payload limit and
frame together.

Bad magic/version, unknown kind, noncanonical or duplicate headers, invalid UTF-8,
truncation, trailing bytes, and size violations fail decoding and stop the
partition. Barrier kind can never become a `StoredRecord`.

## Publication and Deduplication

The adapter maintains one canonical base `rstream.Producer` for all unnamed
physical streams. Lifetime-stable slots serialize each unnamed physical stream's
barriers and publications. `max_streams` bounds the declared physical inventory
served by that producer.

A named producer uses an additional native producer per
`(physical stream, producer name)`. `max_named_producers` bounds all lifetime
named slots and resources. Slots are not an eviction cache. A producer name must
also fit the stream's character limit and the RabbitMQ protocol's 255 UTF-8-byte
limit.

RabbitMQ named publishing IDs must start at one. ID zero is rejected because the
pinned sequence query cannot distinguish no sequence from sequence zero.

Within one process, retrying the same ID and exactly equal request returns
`DEDUPLICATED`; changed content raises `PublishingConflictError`; and an older ID
raises `StalePublishingIdError`. After process restart, an equal broker sequence
without local content association returns `INDETERMINATE`, even if the caller
believes the content is equal.

The current adapter emits these receipt outcomes:

| Outcome | Adapter condition |
| --- | --- |
| `CONFIRMED` | `send_wait` completed under the confirm deadline |
| `DEDUPLICATED` | Exact request matched the local confirmed named coordinate |
| `BACKPRESSURED` | Local pending count or byte admission rejected the send |
| `TIMED_OUT` | Confirm deadline expired; acceptance is indeterminate |
| `INDETERMINATE` | Driver send error or broker sequence exists without local content association |

Cancellation does not produce a receipt. The current adapter propagates
`asyncio.CancelledError` and does not expose whether cancellation happened before
or after native send began. Conservatively treat cancellation of `append()` or a
Tori Py publisher call as acceptance-unknown: do not automatically resend, and
use the same reconciliation or exact named-retry policy as `INDETERMINATE`.

Validation, lifecycle, stale-ID, conflicting-ID, and frame failures raise
core/adapter typed errors instead of returning `REJECTED` or `CLOSED` receipts.
In this provisional release, topology operations, named-producer resource
startup, and publisher-sequence queries can also surface native `rstream`
exceptions or `TimeoutError`; callers must not assume every non-receipt failure
is wrapped in `RabbitMqPersistentStreamsError`. Induced NACK classification
remains an open release gate, so do not
assume all negative confirms map to a definitive rejection.

RabbitMQ confirmation establishes broker acceptance only. It does not establish
consumer execution, exactly-once effects, append offset, or per-message fsync.
The adapter never automatically retries accepted, timed-out, or indeterminate
sends.

## Backpressure

Adapter publication admission rejects before native send when either condition is
true:

```text
pending count >= max_pending_count
or
pending bytes + (serialized AMQP bytes + 64) > max_pending_bytes
```

It returns a `BACKPRESSURED` receipt with
`local-admission-rejected`. This is separate from Tori Py runtime saturation,
which raises `StreamPublicationSaturatedError` before calling the adapter.

Consumer intake uses `initial_credit == 1`, a finite per-lease callback queue,
and serial in-flight processing. Focused stress coverage demonstrated no more
than one credited driver frame plus the configured adapter queue under a blocked
handler. Re-qualify memory and callback behavior for the exact driver and load.

## Reads and Bounds

`bounds()` always returns `None`. RabbitMQ chunk metadata cannot provide a record
end and cannot prove an append. When a retention gap is detected, the current
adapter nevertheless attaches `AvailableBounds(earliest, earliest)` to
`RetentionGapError` as a carrier for the observed low watermark. Only
`earliest_offset` is meaningful in that object; its `end_offset` is not a known
end and must never be used to choose a reset or infer an append.

A finite `read()`:

1. Checks the StreamStats low watermark.
2. Publishes a confirmed unique barrier to the physical stream.
3. Subscribes at the requested exact offset.
4. Rechecks retention after native subscription to close a race.
5. Collects up to `limit` records or through the barrier.
6. Hides all barrier records and returns `RecordPage(..., bounds=None)`.

Reads therefore require write permission and add control records that can create
additional sparse offsets. If the barrier is not observed within
`operation_timeout`, the snapshot read fails rather than inventing an end.

StreamStats `first_chunk_id` is used only as a low watermark. It detects a
requested offset below retained history. The retention-error compatibility
object described above is not complete public bounds.

## TLS and SASL

Enable TLS with a trusted CA:

```python
from tori_py_persistent_streams_rabbitmq import (
    RabbitMqConnectionOptions,
    RabbitMqTlsOptions,
    SaslMechanism,
)

connection = RabbitMqConnectionOptions(
    host="streams.example",
    username="member-service",
    password=secret_password,
    sasl_mechanism=SaslMechanism.EXTERNAL,
    tls=RabbitMqTlsOptions(
        ca_file="/run/secrets/rabbitmq-ca.pem",
        certificate_file="/run/secrets/client.pem",
        private_key_file="/run/secrets/client-key.pem",
        server_hostname="streams.example",
    ),
)
```

TLS always requires certificate trust and hostname verification. Client
certificate and private key must be supplied together. An explicit
`server_hostname` must equal the configured advertised endpoint. `EXTERNAL` SASL
requires TLS.

The pinned regular producer/consumer API supports `PLAIN` and `EXTERNAL`. Super
Stream declaration and inspection require `PLAIN` because
`rstream==1.0.1` does not expose the regular producer's SASL selector through
`SuperStreamProducer`. A multi-partition configuration therefore rejects
`EXTERNAL`.

Real certificate-chain acceptance, rotation, and mutual-TLS tests remain
environment-specific release gates.

## Disconnect and Reconnect

Driver automatic recovery is deliberately disabled. Its cached subscription
replay cannot be fenced through the adapter's topology and cursor preparation.

A producer, tracker, metadata, or lease connection close callback advances the
resource generation, closes intake, cancels an in-flight broker checkpoint, and
fails the adapter closed. The existing adapter does not become accepting again.
Replace it only after the old process is definitively stopped.

Do not construct a replacement while an old single-instance process might still
handle records. For external stores, stale-owner fencing is still required even
after broker loss.

## Provisional Gates

The following remain blockers for an unconditional production-readiness claim:

- Complete core `PersistentLog` conformance under the adapter's explicit
  acquire-before-start lifecycle.
- Induced NACK classification.
- Disconnect-time checkpoint certainty and blackhole fault coverage.
- Full external-store multi-replica fencing evidence.
- Full Super Stream SAC movement and multi-node placement/failover.
- Real TLS certificate acceptance, rotation, and mutual-TLS coverage.
- Broader retention and checkpoint-retention hardening.
- Complete cluster, security, operations, and residual-risk review.

Use the [operations guide](operations.md) for preflight and recovery. Do not
weaken a rejected or unproven capability in application code.
