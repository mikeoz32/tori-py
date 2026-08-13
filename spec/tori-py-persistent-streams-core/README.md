# Persistent Streams Specifications

Status: implemented.

This directory governs the framework-neutral `tori-py-persistent-streams-core`
distribution. Its architecture and delivery order are recorded in
[`TORI_PY_PERSISTENT_STREAMS_CORE_ARCHITECTURE.md`](../../TORI_PY_PERSISTENT_STREAMS_CORE_ARCHITECTURE.md)
and
[`TORI_PY_PERSISTENT_STREAMS_CORE_IMPLEMENTATION_PLAN.md`](../../TORI_PY_PERSISTENT_STREAMS_CORE_IMPLEMENTATION_PLAN.md).

The first slice includes core contracts, an in-memory semantic reference, and a
reusable conformance suite. It does not claim durable persistence.

## Phase Map

| Phase | Main result |
| --- | --- |
| PS0 | [Workspace boundary, public contracts, and artifact foundation](phase-ps0-workspace-and-contracts.md) |
| PS1 | [Immutable records, logical streams, routing, append/read, and start modes](phase-ps1-records-routing-and-log.md) |
| PS2 | [Consumer ownership, checkpoint strategies, and poison-record processing](phase-ps2-consumers-and-checkpoints.md) |
| PS3 | [In-memory reference, controlled retention, and reusable conformance](phase-ps3-inmemory-and-conformance.md) |
| PS4 | [End-to-end acceptance, artifacts, review, and release gates](phase-ps4-acceptance-and-release.md) |

Every phase file defines entry criteria, deliverables, invariants, failure
behavior, tests, and exit criteria. Do not resolve a missing contract silently in
code.

## Cross-Phase Invariants

1. Distribution name is `tori-py-persistent-streams-core`; import name is
   `tori_py_persistent_streams_core`.
2. Runtime code depends only on the Python standard library.
3. The package never imports CQRS, ToriPy, RabbitMQ, SQLAlchemy, PostgreSQL,
   Pydantic, msgspec, or application code.
4. Records carry mandatory UUID identity, opaque bytes, immutable headers, and a
   non-empty byte partition key.
5. Logical streams have explicit immutable positive partition counts.
6. Each stream defensively copies and freezes a deterministic, copyable,
   immutable-value `PartitionRouter` and its hashable `compatibility_key`; core
   provides a versioned SHA-256 default.
7. Offsets are non-negative and strictly increasing with allowed gaps, and imply
   no order across partitions or streams.
8. Public reads are finite, partition-local, offset-ordered, and have no
   `last_chunk` or permanent end-of-stream marker.
9. Unnamed mode requires no publishing-ID state or exclusivity. Named producer
   IDs increase per logical stream, physical partition, and producer name.
10. A matching retry returns a receipt for one accepted publication; stale or
    conflicting reuse fails explicitly.
11. One consumer group has at most one active fenced owner per partition.
12. A `ResumeCursor` is either an initialized inclusive start cursor or the last
    successfully processed record offset; it never relies on `N + 1`.
13. Existing checkpoints override configured start modes.
14. Beginning starts at the retained beginning; end starts at a captured end cursor;
    exact offsets are inclusive; timestamp starts at the first record at or after
    the target; relative time resolves from an injected/current aware clock.
15. A newly resolved start is compare-and-created as an initialized cursor before
    delivery so restart cannot recalculate end or relative-time progress.
16. Processing is at least once: handler success precedes cursor advancement.
17. A handler or checkpoint failure stops that partition and does not advance
    progress.
18. Poison records are not skipped, retried automatically, or dead-lettered.
19. External checkpoints are not atomic with handler side effects.
20. One `(stream, group)` fixes its complete checkpoint strategy only after
    successful initialization. External strategy identity is stable and the
    in-memory reference also binds the exact store object; pending matching
    reservations permit concurrent partition initialization, and failed or
    cancelled initialization releases its reservation.
21. Stale starts and checkpoints raise typed `RetentionGapError`; they never
    auto-reset.
22. Beginning mode explicitly accepts the current retained beginning.
23. The in-memory implementation is a semantic reference, not durable storage.
24. Append returns a `PublishReceipt` with record identity, selected partition,
    and confirmation facts, never an offset or `StoredRecord`.
25. Future adapters run the reusable conformance suite plus adapter-specific
    durability and infrastructure tests.
26. Every dependency, test, build, and quality command runs through `uv`.
27. A lease reserves at most one exact in-flight delivery. Only that delivery may
    be checkpointed, and transfer never overlaps it with a new owner's handler.
28. Logs expose immutable start-mode capabilities and reject unsupported starts
    before ownership or intake.
29. External checkpoint I/O failures are typed, retain their cause and relevant
    cursor, stop runtime intake, and never wrap cancellation or process control.
30. Relative starts are bounded by `max_relative_age_days`; clock arithmetic
    overflow is a typed validation failure.
31. Required portable conformance cases are never capability-optional; only
    controlled retention setup is gated on an administrative capability.
32. `PersistentStreamAdapter` adds adapter-neutral `start()` readiness and
    `quiesce()` intake-handoff barriers without changing `PersistentLog`
    conformance.
33. Timeout, cancellation, or disconnect during checkpoint storage/query is
    indeterminate: recovery may observe either the old or new cursor unless the
    adapter first produced a definitive result.
34. Broker-managed checkpoints are supported only in explicitly configured
    single-instance deployments. A shared external checkpoint store supports
    multi-replica deployments only when every replica uses a replica-unique owner ID
    and the store provides atomic fence replacement and exact-owner save validation.

## Change Control

1. Update the relevant PS phase specification before changing agreed behavior.
2. Update the architecture when package boundaries or semantic guarantees
   change.
3. Update the implementation plan when phase order, scope, or non-goals change.
4. Add or update portable conformance coverage for changed public behavior.
5. Keep production adapter decisions in separate architecture and executable
   specifications.
