# ES4: Repository and Unit of Work

## Entry Criteria

- ES3 exit criteria pass.

## Deliverables

- Generic event-sourced repository with explicit stream category, aggregate
  factory, exact aggregate type, stable ID encoder, configurable bounded page
  size, registry, and transaction.
- Unit of Work that owns one transaction and all aggregate enlistments.
- Optional and required load operations plus stage-save and explicit commit.

## Invariants

- Repository load reads finite pages from one repeatable snapshot and never
  returns partially replayed state.
- ID encoding is deterministic and collision-free within category/tenant policy.
- Save stages the complete pending snapshot at the aggregate committed version.
- Save validates type and aggregate/UoW lifecycle before invoking event codecs.
- One aggregate and one stream can be enlisted only once per Unit of Work.
- Commit prevalidates every aggregate before storage I/O.
- Commit synchronously enters `COMMITTING`; competing save, rollback, transaction
  access, and second commit are rejected.
- Confirmed storage success performs a non-failing local version transition.
- Conflict, duplicate identity, indeterminate outcome, or malformed commit result
  faults every aggregate enlisted in the atomic Unit of Work.
- Confirmed pre-commit infrastructure failure and deliberate rollback release
  aggregates while preserving pending events.
- Only `ConfirmedCommitError` or raw adapter-confirmed rollback cancellation may
  classify commit as a reusable non-commit; unknown failures are indeterminate.
- Cleanup failure after confirmed commit raises `ConfirmedCommitCleanupError`
  carrying the confirmed result.
- Framework-owned aggregate lifecycle methods are invoked through
  `AggregateRoot`; only `_apply()` is application-overridden.

## Failure Behavior

- Required load of a missing stream raises `AggregateNotFoundError`.
- Wrong aggregate/stream identity, repeat save, duplicate stream instances, and
  commit-state mutation raise typed errors.
- Context exit without commit rolls back and releases aggregates.

## Tests

- Create, save, reload, replay, and no-op save.
- Multi-page load and schema upcasting.
- Multi-aggregate atomic commit.
- Repeated save and duplicate stream aggregate rejection.
- Confirmed failure, optimistic conflict, malformed result, and indeterminate
  outcome aggregate state.
- Commit-vs-stage/rollback/commit races and post-commit cleanup failure.

## Exit Criteria

- Repository/UoW contracts pass against `InMemoryEventStore` and failure fakes.
