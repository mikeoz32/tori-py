# Persistent Streams Implementation Plan

Status: implemented; PS0-PS4 package, conformance, acceptance, and artifact
gates pass.

Architecture: [`TORI_PY_PERSISTENT_STREAMS_CORE_ARCHITECTURE.md`](TORI_PY_PERSISTENT_STREAMS_CORE_ARCHITECTURE.md).

The executable phase map and cross-phase invariants are recorded in
[`spec/tori-py-persistent-streams-core/README.md`](spec/tori-py-persistent-streams-core/README.md). This
plan creates only the framework-neutral package, its in-memory semantic
reference, and its reusable conformance suite.

## 1. Goal

Build a generic append-only persistent-log abstraction for Python 3.14. The
first slice proves partition routing, offset ordering, group ownership,
checkpointing, start positions, producer retry, poison-record stops, and
retention-gap handling without claiming durability.

The acceptance target is an isolated in-memory flow with multiple partitions,
multiple owners, both checkpoint strategies, every start mode, named-producer
retry, poison-record redelivery, and controlled retention.

## 2. Package Boundary

Create one workspace distribution:

- distribution: `tori-py-persistent-streams-core`;
- import package: `tori_py_persistent_streams_core`;
- runtime dependencies: Python standard library only;
- no dependency on another workspace distribution.

The package MUST remain independent of CQRS, ToriPy, RabbitMQ, SQLAlchemy,
PostgreSQL, msgspec, Pydantic, and application code. The in-memory
implementation and conformance helpers are included in the same distribution.

## 3. Delivery Order

### PS0: Workspace and contracts

1. Add the executable PS0 specification before workspace changes.
2. Add `packages/tori-py-persistent-streams-core` to the `uv` workspace.
3. Establish the standard-library-only dependency boundary, package facade,
   `py.typed`, and public protocol inventory.
4. Add import-boundary, wheel, and source-distribution smoke checks.
5. Add each later executable phase specification before its behavior code.

### PS1: Records, streams, routing, and append/read

1. Implement validated immutable stream definitions, append requests,
   `PublishReceipt`, stored records, optional available bounds, pages, limits,
   and typed errors. Receipts contain no offset or `StoredRecord`.
2. Implement a deterministic immutable-value `PartitionRouter` contract and the
   versioned SHA-256 default router, defensively copied and frozen per stream.
3. Define asynchronous declaration, append, optional available-bound, and bounded partition
   read protocols.
4. Implement beginning/end/exact/timestamp/relative start value objects and
   deterministic resolution contracts.
5. Implement optional named producer coordinates and publishing-ID validation.
6. Test byte/header immutability, offsets, timestamps, limits, and the absence of
   any global-order or last-chunk contract.

### PS2: Consumer groups and checkpoints

1. Define ownership, assignment, fencing, and subscription lifecycle contracts.
2. Define broker-managed and stable-identity external resume-cursor strategies
   with distinct initialized-start and last-successful-offset states.
3. Implement compare-and-create start initialization and cursor-after-success
   processing order.
4. Stop one partition on handler or checkpoint failure without advancing it.
5. Translate external persistence failures with causes/cursors, preserve
   `CancelledError`, and reject stale owners and checkpoint regression.
6. Specify typed retention-gap propagation for starts and checkpoints.

### PS3: In-memory reference and conformance

1. Implement `InMemoryPersistentLog` with isolated state and serialized state
   transitions.
2. Implement deterministic assignment, fencing, broker-managed checkpoints, and
   external-checkpoint integration.
3. Implement unnamed publication, per-physical-partition named-producer retry,
   and controlled trimming.
4. Build a reusable public conformance suite against adapter factories.
5. Run the complete suite against the in-memory reference.
6. Add concurrent compare-create, cancellation, ownership-transfer/fencing,
   checkpoint-failure, validation, lifecycle, and retention-gap coverage.

### PS4: Acceptance and release

1. Add the complete multi-partition in-memory acceptance flow.
2. Prove both checkpoint strategies and explicitly demonstrate the external
   checkpoint/side-effect failure window.
3. Prove all start modes, producer retry, poison redelivery, and retention-gap
   behavior.
4. Review public exports, typing, errors, lifecycle, resource limits, and docs.
5. Build wheel and source distributions and smoke-test both in isolated `uv`
   environments.
6. Run focused and repository-wide quality gates.

## 4. Required Semantic Order

Implementation MUST preserve these dependencies:

1. Immutable values and routing exist before log behavior.
2. Log append/read behavior exists before group consumption.
3. Ownership and checkpoint protocols exist before the processing runner.
4. The in-memory reference consumes public contracts rather than defining
   private alternatives.
5. Conformance cases target public protocols and do not special-case in-memory
   internals except controlled retention setup.
6. Acceptance begins only after the reference passes conformance.

## 5. Verification Targets

All Python and build commands run through `uv`:

```text
uv run pytest packages/tori-py-persistent-streams-core/tests
uv run ruff check .
uv run ruff format --check .
uv run ty check packages/tori-py-persistent-streams-core/src packages/tori-py-persistent-streams-core/tests
uv build --package tori-py-persistent-streams-core
uv run pytest
```

Artifact verification MUST install wheel and source distributions independently,
import the public facade, and run a minimal append/consume/checkpoint flow without
installing another workspace package.

## 6. Explicit Non-Goals

- No durable adapter or durability claim.
- No RabbitMQ, Kafka, Redis, PostgreSQL, or filesystem implementation.
- No CQRS, ToriPy, SQLAlchemy, Pydantic, or msgspec dependency.
- No global ordering, cross-partition transactions, or exactly-once processing.
- No automatic retry, dead letters, poison skipping, or checkpoint reset.
- No retention scheduler, compaction, stream deletion, or partition resizing.
- No `last_chunk` or equivalent end-of-stream API.
- No application serialization or schema registry.

## 7. Follow-Up Adapter Obligations

A later production adapter plan MUST separately define:

1. Durable append acknowledgement and indeterminate outcomes.
2. Broker topology, partition mapping, ownership leases, and rebalance recovery.
3. Durable checkpoint and named-producer state retention.
4. Broker outage, reconnect, cancellation, and shutdown behavior.
5. Retention configuration, monitoring, backup, and operational recovery.
6. Adapter-specific conformance fixtures and integration tests.
7. Security, tenancy, authorization, encryption, and credential handling.
8. Any application-owned inbox or transactional side-effect design.
