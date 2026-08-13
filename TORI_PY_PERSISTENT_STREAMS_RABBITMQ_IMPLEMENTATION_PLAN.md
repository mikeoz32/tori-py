# RabbitMQ Persistent Streams Implementation Plan

Status: RPS0-RPS7 incomplete. The adversarial review invalidated the previous
RPS1-RPS4 completion claims. Focused real-broker coverage exists for barriers,
graceful SAC takeover, stale-owner rejection, producer isolation, bounded intake,
blocked-handler quiescence, and fail-closed disconnects. Full conformance,
external-store multi-replica fencing, TLS/fault tests, Super Stream failover, and
release review remain gates.

Mechanical import-order edits under the existing ToriPy microservices examples and
tests are intentionally retained but must be isolated in a separate later commit;
no tori-py-persistent-streams-core changes should be mixed into those files.

## Delivery Principles

1. Use exactly `rstream==1.0.1` on Python 3.14 through supported public APIs plus
   the one isolated, fail-fast StreamStats compatibility module.
2. Keep core `PersistentLog` conformance separate from ToriPy lifecycle/execution
   conformance.
3. Return offset-free `PublishReceipt` values; observe offsets only on reads or
   consumption.
4. Support unnamed producers without publishing-ID state or exclusivity.
5. Scope named IDs per physical producer and never auto-retry uncertainty.
6. Preserve sparse offsets and tagged `ResumeCursor` semantics without `N + 1`.
7. Reject unsupported start/cursor combinations before intake.
8. Use only inspectable topology checks; operator policy/retention stays preflight.
9. Run all dependencies, tests, builds, and services through `uv`.

## Delivery Order

### RPS0: Driver Feasibility

- Create only the package boundary, exact dependency pin, risk register, and
  spike tests.
- Prove Python 3.14, confirms, reconnect, regular/Super Streams, SAC, credit,
  named/unnamed producers, checkpoint internal records, store/query uncertainty,
  retention, timestamp/clamp behavior, all start modes, and append timestamps.
- Prove safe initialized-cursor representation or enumerate and reject unsupported
  combinations, including broker-managed `END` on an empty stream.

Exit gate: approve independently proven capabilities and explicitly reject modes
whose semantics cannot be proven. Never advertise a silent approximation.

Result: incomplete. A dedicated metadata `Client` proved
publisher sequence queries; the pinned `0x1c` bridge proved StreamStats and a
retention low watermark; tagged uint64 broker cursors proved both cursor kinds and
empty-stream `END`; and the canonical binary envelope round-tripped through the
broker. Timestamp/relative starts remain unsupported. Offset-store fault
certainty, TLS, retention/checkpoint hardening, and failure tests remain gates.

### RPS1: Configuration and Resources (Incomplete)

- Implement bounded redacted options, sync/async ToriPy adapter modules,
  owned native resources, generation fencing, and capability publication.

### RPS2: Topology (Incomplete)

- Idempotently create explicit regular/Super Stream topology.
- Inspect only kind and partition topology exposed by supported APIs.
- Document policy, retention, permissions, replication, and placement as
  operator preflight, not runtime verification.

### RPS3: Envelope and Publishing (Incomplete)

- Freeze and test the version-1 binary body envelope before first publication;
  use only flat standard `message-id` and `content-type` properties.
- Realize the stream's configured router through exact partition binding keys.
- Support unnamed mode and per-physical-partition named producers.
- Return receipts with UUID, partition, and confirmation facts only.

### RPS4: SAC, Starts, and Resume Cursors (Incomplete)

- Implement one SAC identity per group and physical partition with finite credit.
- Implement beginning/end/exact only and reject timestamp/relative capabilities.
- Store tagged cursors in broker tracking with the frozen uint64 codec and decode
  before selecting inclusive subscription plus last-successful filtering.
- Stop without cursor advancement on every failed attempt.

### RPS5: Reconnect, TLS, and Backpressure (Incomplete)

- Fence generations, bound callbacks/confirms/credit/shutdown, verify TLS, and
  prove reconnect never bypasses topology/cursor preparation.

### RPS6: Conformance and Failure Matrix

- Run core `PersistentLog` conformance against `RabbitMqPersistentLog`.
- Run ToriPy lifecycle/execution conformance against the configured factory/runtime.
- Run real-broker envelope, start, retention, SAC, confirm, and reconnect faults.

### RPS7: Acceptance and Release

- Build isolated artifacts and complete reliability, security, operations,
  compatibility, and residual-risk review against a real cluster.

## Deferred

- Management HTTP/API capability and runtime policy verification.
- Dynamic partitions, sub-entry batching, compression, server filtering, and RPC.
- Exactly-once processing or transactional effects/cursors.
