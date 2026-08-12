# persistent-streams-rabbitmq

Conditional RabbitMQ native Streams adapter for `persistent-streams` and
`nestpy-persistent-streams`. It requires CPython 3.14, RabbitMQ 4.1, the
`rabbitmq_stream` plugin, and exactly `rstream==1.0.1`.

## Supported Contract

- Regular Streams and fixed-partition Super Streams with explicit `CREATE` or
  `REQUIRE_EXISTING` declaration.
- Core SHA-256 routing (or the configured core router) mapped to exact Super
  Stream binding keys `0..partition_count-1`.
- Confirmed named and unnamed publication with finite count, byte, and deadline
  admission. Receipts contain no offset. Accepted or indeterminate sends are
  never automatically retried.
- One canonical base `rstream.Producer` serves every unnamed physical stream;
  `max_streams` bounds its internal per-stream publisher cache and counts physical
  regular/Super Stream partitions. Lifetime-stable coordinate slots serialize
  unnamed barriers/publications, while `max_named_producers` bounds all additional
  named producer resources and slots.
- Named producer IDs scoped to each physical partition. Reuse the same record
  ID, producer name, partition key, and publishing ID for an explicit retry.
  Named IDs start at one because the pinned public API cannot distinguish a
  missing producer sequence from publishing ID zero.
- Canonical PSRM v2 binary body with explicit record/barrier kind and
  `application/vnd.persistent-streams.record.v2` content type.
- Beginning, end, and exact-offset starts. Timestamp and relative-time starts
  are rejected before subscription.
- Sparse physical offsets, serial partition delivery, finite callback queues,
  stable hashed SAC identities, broker-tagged cursors, and external core
  checkpoint strategies.
- Barrier-delimited `END` and finite reads; public bounds are unavailable rather
  than inferred from chunk metadata.
- Prepared leases with no intake until `start`; standby SAC registration counts as
  readiness and delivery waits for activation. Quiesce, close, callbacks, and
  transfers are deadline bounded.

The adapter verifies only public inspectable kind, partition, and binding facts.
It sends finite retention settings on creation but does not report effective
policy, retention, replication, placement, or permissions as verified.

## Nestpy

```python
from nestpy_persistent_streams import PersistentStreamsModule
from persistent_streams_rabbitmq import (
    RabbitMqConnectionOptions,
    RabbitMqPersistentStreamsModule,
    RabbitMqPersistentStreamsOptions,
)

rabbit = RabbitMqPersistentStreamsModule.for_root(
    RabbitMqPersistentStreamsOptions(
        RabbitMqConnectionOptions(
            host="streams.example",
            username="application",
            password="secret",
        )
    )
)
streams = PersistentStreamsModule.for_root(options, imports=[rabbit])
```

Constructing options, the deferred module, factory, or log performs no I/O.
`for_root_async()` resolves secrets/configuration through normal Nestpy injection.
The broker-free
[`examples/nestpy/persistent_streams`](../../examples/nestpy/persistent_streams/README.md)
application demonstrates the same inventory and publisher surfaces; its README
includes the RabbitMQ adapter substitution.

## Important Limits

RabbitMQ confirms broker acceptance, not consumer execution, exactly-once effects,
per-message fsync, or an append offset. SAC is not a transaction. Super Streams
use PLAIN SASL because pinned `SuperStreamProducer` does not expose its regular
producer's SASL selector; EXTERNAL is rejected for that topology.

Cross-restart named-publishing content association is unsupported; an existing
broker sequence without local association returns `INDETERMINATE`.

Broker-managed checkpoints are supported only in explicitly configured
single-instance deployments. A shared external checkpoint store supports
multi-replica deployments only when every replica uses a replica-unique owner ID
and the store provides atomic fence replacement and exact-owner save validation.

Operators must ensure old and replacement single-instance processes never
overlap, including after disconnect.

Checkpoint store/query timeout, cancellation, or disconnect is indeterminate:
recovery may observe either the old or new cursor. The adapter stops intake and
never promises that the cursor remained unchanged. Automatic reconnect is
disabled and a disconnect fails the adapter closed; construct a new adapter only
after the old single-instance process is definitively stopped.

See [OPERATIONS.md](OPERATIONS.md) for broker and security preflight and the
remaining release gates.

The final structural review findings are addressed, but release review remains
pending. Repository-wide `pytest` still has one unrelated migration checksum
failure; focused suites, Ruff, format, Ty, and artifact verification pass. These
results do not complete the conditional RPS operational gates.
