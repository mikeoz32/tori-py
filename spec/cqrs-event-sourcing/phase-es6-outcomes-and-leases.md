# ES6: Outcomes and Repository Operation Leases

## Purpose

Expose exact Unit-of-Work final outcomes and an optional framework-neutral lease
check for integrations without changing standalone repository behavior.

## Contract

- `EventSourcingUnitOfWork.outcome` is a read-only union of confirmed commit,
  confirmed non-commit, and indeterminate commit after final classification.
- Confirmed commit carries validated `CommitResult`.
- Confirmed non-commit and indeterminate outcomes carry their original causes
  where present.
- Outcome access before classification raises a typed lifecycle error.
- Unknown failure after commit begins and malformed commit results are
  indeterminate.
- Validated commit remains confirmed through later cleanup failure.
- `EventSourcedRepository` accepts an optional operation lease/callable.
- Every public load/save operation checks the lease before touching transaction
  or aggregate state.
- No lease preserves existing standalone behavior and API ergonomics.
- Lease failures propagate unchanged and do not mutate aggregate/UoW state.

## Tests

- Every ES4 commit, rollback, conflict, cancellation, malformed-result,
  indeterminate, and cleanup path has the exact outcome.
- Outcome is immutable and unavailable while active/committing.
- Lease permits owner operations and rejects before load/save side effects.
- Async load and synchronous save both check the lease.
- Existing repositories without a lease retain all ES0-ES5 behavior.

## Exit Criteria

- Framework integrations never infer durable outcomes from catch-all exception
  lists and can invalidate escaped repositories safely.
