# ES3: EventStore and In-Memory Reference

## Entry Criteria

- ES2 exit criteria pass.

## Deliverables

- Runtime-checkable EventStore and transaction protocols.
- Immutable commit result and typed concurrency, identity, lifecycle, and
  indeterminate-outcome errors.
- Atomic `InMemoryEventStore` reference implementation.
- Reusable EventStore contract tests.

## Invariants

- A transaction reads one repeatable committed snapshot established on entry.
- Reads use finite version/position pagination and exclude staged appends.
- One transaction stages at most one non-empty append batch per stream.
- Commit validates every expected version and event ID before mutation.
- Commit synchronously enters `COMMITTING` before its first await and rejects
  concurrent read, append, rollback, and commit operations.
- Commit is all-or-none across every staged stream.
- Stream versions are contiguous; global positions follow staging and event
  order.
- The in-memory store has a known outcome under cancellation and never claims
  durability.

## Failure Behavior

- Optimistic conflicts expose stream, expected, and actual versions.
- Duplicate event IDs and repeated stream append fail before mutation.
- Leaving without commit rolls back.
- Closed transaction use raises a lifecycle error.
- Durable adapters report unknown acknowledgement as an indeterminate outcome;
  the in-memory reference never fabricates that outcome.
- Raw cancellation means the adapter confirms no commit; ambiguous cancellation
  is translated to `IndeterminateCommitError`.

## Tests

- Missing stream, ordered stream/global pagination, and immutable results.
- Atomic multi-stream commit and rollback.
- Concurrent writers where exactly one expected-version append succeeds.
- Duplicate IDs, repeated stream staging, limits, cancellation, and lifecycle.
- Repeatable reads while another transaction commits.

## Exit Criteria

- The in-memory implementation passes all reusable store contracts.
