# RPS0: Workspace and Driver Feasibility

## Status

Incomplete after adversarial review. The feasibility spike remains evidence, but
its former end, producer-restart, and automatic-recovery conclusions were revised.

## Deliverables

- Installable typed package boundary pinned to `rstream==1.0.1` and Python 3.14.
- Public-API/source audit and real-broker executable feasibility matrix.
- Exact capability report that either unlocks RPS1 or blocks the proposal.

## Required Proofs

- Regular Streams, Super Streams, metadata, binding routing, SAC, credit, and
  callback cancellation.
- ACK/NACK, timeout/disconnect ambiguity, named and unnamed producers, physical
  producer sequence queries, and reconnect generation behavior.
- Beginning, end, exact offset, timestamp, and relative-after-timestamp-resolution
  starts; timestamp ties, future timestamps, native clamp, and retention-gap
  detection.
- Broker tracking internal checkpoint records, store/query ordering, disconnect
  uncertainty, retention of checkpoints, and interaction with data retention.
- Safe initialized `ResumeCursor` representation, especially `END` on an empty
  stream, or an exact startup rejection matrix for unsupported combinations.
- Broker/adapter append timestamp available on consumed records.
- Canonical AMQP 1.0 envelope interoperability and unknown-field behavior.

The spike must not derive a publish position from available bounds. Private APIs
and fabricated semantics are invalid.

## Exit Criteria

Each advertised behavior is proven through public APIs or the one pinned isolated
compatibility bridge on Python 3.14. Unproven modes are rejected explicitly.

## Result

Executed on CPython 3.14.6 with `rstream==1.0.1` against RabbitMQ 4.1.8 and the
Stream/Stream Management plugins. The package boundary, exact dependency pin,
lazy no-I/O root import, `py.typed`, and isolated spike suite are present.

Proven through the public facade and a real broker:

- regular Stream create/existence/delete;
- Super Stream creation, fixed partitions, binding routing, and deletion, with a
  driver closed-client ordering defect between partition and route operations;
- named and unnamed confirmed sends return publishing IDs and no offsets; exact
  named retry is deduplicated;
- AMQP standard properties and binary body round-trip, with decoded text
  represented as bytes;
- delivered offsets and broker chunk timestamps, FIRST/LAST/NEXT/OFFSET/TIMESTAMP,
  a parked beyond-tail exact offset, inclusive timestamp ties, and a future
  timestamp that natively clamps to NEXT without a public clamp fact;
- offset store/query, with tracking records hidden from delivery but consuming a
  physical offset (`0, 1, 3` data offsets); the management queue detail response
  had no message-count statistic;
- SAC active notification and standby promotion, close/new generation, real
  broker stop/start producer recovery, and TLS constructor shape.

Additional proven bridge evidence:

- `Client.query_publisher_sequence()` returned the named producer's sequence on a
  dedicated metadata connection;
- protocol command `0x1c` returned the exact RabbitMQ 4.1 stats keys
  `first_chunk_id`, `last_chunk_id`, and `committed_chunk_id`; empty values were
  `-1`, and byte retention advanced the first chunk above zero;
- tagged uint64 values round-tripped initialized and last-successful cursors;
  initialized empty `END` survived and delivered the first later record;
- the binary `PSRM` v1 body envelope has a frozen golden vector and round-tripped
  with only flat `message-id` and `content-type` properties;
- fresh Super Stream resource generations avoid the closed locator cache without
  private-state access or monkeypatching.

Still gated or rejected: timestamp/relative starts are rejected because chunk
timestamps do not prove exact per-record append-time semantics and future starts
clamp to NEXT. NACK/fault ambiguity, disconnect-time offset-store certainty,
checkpoint retention, full Super Stream SAC failover/fencing, TLS certificate
acceptance, and retention hardening remain later work.

Exit decision: partial capability-approved. Core invariants were not weakened.
