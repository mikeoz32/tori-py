# RPS6: Conformance and Failure Matrix

Status: incomplete. Focused real-broker Nestpy lifecycle/execution passes;
the complete NACK, disconnect, TLS, blackhole, and cluster failure matrix remains.

## Core Conformance

Run core `PersistentLog` conformance against `RabbitMqPersistentLog`: declaration,
routing, offset-free receipts, named/unnamed publication, sparse consumed offsets,
reads, advertised starts, ownership, tagged cursors, retention gaps, and close.

## Nestpy Conformance

Separately run Nestpy adapter lifecycle/execution conformance against
`RabbitMqStreamAdapterFactory` and its runtime: internal module composition,
topology preparation, callback handoff, pipeline completion, fail-stop behavior,
cursor timing, readiness, reconnect generations, quiescence, and shutdown.

## Real-Broker Matrix

- Canonical envelope interoperability and malformed/unknown/oversized fields.
- Regular/Super Streams, exact binding routing, SAC failover, sparse offsets, and
  every advertised start.
- Retention, timestamp clamp, checkpoint internal records, store/query uncertainty,
  and empty-stream `END` rejection or proven safe support.
- ACK/NACK, disconnect timing, broker restart, callback races, saturation, TLS,
  advertised hosts, and blackholes.
- Python 3.14 and exact `rstream==1.0.1` source-path audit.

## Exit Criteria

No unresolved behavior is hidden behind success, retry, clamp, verification, or
another conformance layer. Any unmitigated required risk blocks release.
