# PS2: Consumers and Checkpoints

Status: implemented.

## Entry Criteria

- PS1 exit criteria pass.

## Deliverables

- Consumer-group subscription, assignment, owner-generation, and lifecycle
  contracts.
- Broker-managed checkpoint operations and an asynchronous external checkpoint
  store protocol.
- Processing runner with handler-then-checkpoint sequencing.
- Typed ownership, checkpoint, lifecycle, poison-record, and checkpoint-storage
  failures.

## Invariants

- A group binds one logical stream and has at most one active owner per
  partition.
- A group fixes one complete checkpoint strategy only after successful
  initialization. External strategies bind a stable identity, and the in-memory
  reference also binds the exact store object. Concurrent partition
  initialization reserves the same pending strategy and failed or cancelled
  initialization releases its reservation.
- Every assignment carries a fence token; revoked owners cannot fetch or
  checkpoint.
- A lease reserves one exact in-flight record. A second fetch fails until that
  delivery is checkpointed, stopped, or released, and no fabricated or later
  record can be checkpointed.
- Forced transfer requests revocation and waits for the old in-flight delivery to
  checkpoint, stop, or release before installing the new generation.
- Records are invoked serially in increasing offset order within a partition.
- Different partitions may progress concurrently without creating a global
  order.
- A `ResumeCursor` distinctly stores an initialized inclusive start or the last
  successfully processed offset and never regresses in observed record order.
- An existing checkpoint overrides the configured start mode.
- A missing checkpoint is compare-and-created from the resolved start before
  first delivery; a concurrent existing value wins.
- The runner awaits successful handler completion before storing that record's
  offset as the last successfully processed position.
- External checkpoints are not atomic with handler side effects or ownership.
- Ownership loss, handler failure, cancellation, and checkpoint failure never
  intentionally advance progress.

Broker-managed checkpoints are supported only in explicitly configured
single-instance deployments. A shared external checkpoint store supports
multi-replica deployments only when every replica uses a replica-unique owner ID
and the store provides atomic fence replacement and exact-owner save validation.

## Failure Behavior

- Handler ordinary failure stops only the affected partition and raises
  `PoisonRecordError` with record and partition coordinates plus the cause.
- Cursor persistence failure stops the partition and exposes the attempted
  last-successful offset or initialized start cursor. Timeout, cancellation, and
  disconnect are indeterminate; either the old or new cursor may later be read.
- External fence/load/compare-create/save failures expose a typed checkpoint
  failure and cause. Runtime load/save failures stop the lease; acquisition
  failures release ownership and strategy reservations.
- Stale-owner fetch/checkpoint and checkpoint regression raise typed errors.
- A stale checkpoint raises `RetentionGapError` and is never auto-reset.
- `CancelledError`, `KeyboardInterrupt`, and `SystemExit` are not converted into
  ordinary poison errors; cleanup does not erase the primary failure.

## Tests

- Exclusive ownership, deterministic transfer seam, fencing, and stale-owner
  rejection.
- Serial in-partition invocation and allowed cross-partition concurrency.
- Broker-managed and external checkpoint load/advance behavior.
- Checkpoint mode, external identity, and exact-store mismatch rejection without
  split progress.
- Handler success before checkpoint, handler failure without checkpoint, and
  checkpoint failure without later delivery.
- Poison partition stop, another partition's progress, reacquisition, and
  redelivery from unchanged progress.
- Cancellation during handler and checkpoint plus ownership cleanup.
- Existing checkpoint precedence over every start mode.
- Concurrent start initialization and stable end/relative-time restart.
- Concurrent same-strategy partition reservations, failed initialization cleanup,
  and cancellation-safe blocked-handler transfer without handler overlap.
- Persistence failure translation and cancellation during external checkpoint
  initialization/load/save without wrapping control flow.

## Exit Criteria

- Consumer and checkpoint contracts pass against protocol fakes without relying
  on in-memory implementation internals.
