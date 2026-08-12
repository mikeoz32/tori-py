# PS3: In-Memory Reference and Conformance

Status: implemented.

## Entry Criteria

- PS0-PS2 exit criteria pass.

## Deliverables

- `InMemoryPersistentLog` implementing all public log and group contracts.
- Isolated stream, partition, producer, ownership, and broker-checkpoint state.
- Deterministic in-memory assignment and generation fencing.
- Controlled trim support for retention tests without offset renumbering.
- Reusable adapter conformance factories and cases under the public testing API.

## Invariants

- Instances share no mutable state and process exit loses all state.
- State transitions are serialized where required to preserve offsets,
  publishing IDs, ownership, and checkpoints under asynchronous concurrency.
- Record append becomes visible atomically with one assigned partition offset.
- Named-producer exact retry cannot append twice under concurrent calls.
- Trimming advances the earliest available bound but preserves offsets,
  producer state, checkpoints, and the removed-time boundary.
- In-memory ownership transfer waits for the old lease's exact in-flight delivery
  to checkpoint or be abandoned before the new generation may process.
- No background worker, disk I/O, hidden retry, automatic retention, or
  durability claim is introduced.
- Conformance tests target public protocols; controlled trim uses an explicit
  testing/administrative capability.
- Required portable conformance cases are unconditional; adapter-specific admin
  cases may be capability-gated without weakening the portable suite.

## Failure Behavior

- Concurrent conflicting producer calls accept at most one request and report a
  typed conflict for the other.
- Stale owners and stale checkpoints fail after transfer or trim without state
  repair.
- Cancellation cannot leave two active owners or partially advance a
  checkpoint.
- In-memory failures never fabricate durable acknowledgement or exactly-once
  guarantees.

## Tests

- The complete reusable conformance suite against fresh in-memory factories.
- Concurrent append with strictly increasing, potentially sparse partition
  offsets and immutable records.
- Cross-partition append proving only partition-local order is asserted.
- Concurrent producer retry/conflict and sequence state after trim.
- Multi-owner assignment, transfer, fencing, cancellation, and release.
- Exact in-flight checkpoint validation and blocked-handler transfer with no
  overlapping handler execution.
- Controlled trim, available bounds, stale reads, stale starts, and stale cursors.
- Both checkpoint strategies, all starts, poison stops, and redelivery.
- Resource limits and lifecycle closure under concurrent operations.
- Concurrent initialized-cursor compare-create, external checkpoint failures and
  cancellation, strategy identity/store binding, and closed lifecycle coverage.

## Exit Criteria

- `InMemoryPersistentLog` passes every common conformance case.
- The suite can be imported and parameterized by a future adapter without
  importing in-memory implementation internals.
