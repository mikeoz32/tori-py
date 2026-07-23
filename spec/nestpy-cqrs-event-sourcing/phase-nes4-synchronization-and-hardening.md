# NES4: Synchronization and Hardening

## Entry Criteria

- NES0-NES3 pass.

## Deliverables

- Request-scoped `CommandSynchronization`.
- Outcome-specific callback execution and finalization errors.
- Caller/handler cancellation distinction.
- Same-bus nested-command rejection before enqueue.
- Event-publication boundary and shutdown hardening.

## Synchronization Invariants

- Callback registration is allowed only while the handler body is active.
- Confirmed-non-commit compensations run in reverse registration order.
- Commit and indeterminate notifications run in registration order.
- Ordinary callback failures are collected and remaining callbacks are attempted.
- A callback control-flow exception stops callback execution and remains control
  flow with typed transaction outcome context.
- Callback failure never changes persistence classification.
- Confirmed commit callback failure carries commit result and handler result.
- Confirmed non-commit callback failure retains the original handler/commit error.
- Indeterminate callback failure retains the indeterminate cause.
- Late child-task registration or use raises
  `CommandSynchronizationStateError`.
- Indeterminate callbacks are reconciliation notifications, not destructive
  compensation.

## Cancellation Invariants

- Cancelling/timing out a bus caller after acceptance does not cancel or classify
  the worker-owned command.
- Handler cancellation before commit rolls back and runs compensation.
- Cancellation during commit uses only the store/UoW typed outcome.
- Shutdown cancellation obeys the same rules and cannot invent rollback proof.
- Cancellation is surfaced as `CommandCancellationError`, a `CancelledError`
  subtype carrying typed outcome and secondary failures; other control flow is
  never wrapped as an ordinary adapter exception.
- `KeyboardInterrupt` and `SystemExit` preserve object identity; outcome and
  secondary failures are attached as notes and structured logs.

## Nested Dispatch and Publication

- Same active CommandBus nested dispatch raises core-owned
  `NestedCommandDispatchError` before enqueue.
- The rejected nested command never executes later.
- Nested queries run independently and observe committed state only.
- Event publication is never automatic.
- Direct publication from a handler is documented as pre-commit/non-transactional.
- `after_commit` publication is post-commit but non-durable.
- Reliable production publication requires a transactional outbox.

## Tests

- FIFO/LIFO callback order, async callbacks, all-attempt behavior, and failures.
- External content compensation for handler failure, conflict, known
  cancellation, and confirmed rejection.
- No destructive compensation for indeterminate or confirmed commit outcomes.
- Late callback registration and background task transaction use.
- Caller cancellation followed by eventual confirmed commit.
- Handler cancellation before and during commit.
- Same-bus nested command rejection and absence of delayed execution.
- Nested query visibility and no automatic EventBus delivery.
- Graceful shutdown drain and bounded cancellation/finalization.

## Exit Criteria

- External side-effect coordination never weakens or obscures the persistence
  outcome.
