# NES3: Transactional Commands

## Entry Criteria

- NES0-NES2 pass.

## Deliverables

- `@use_event_sourcing(key=...)` CQRS interceptor metadata convenience.
- Request-scoped event-sourcing command interceptor.
- Transaction coordinator owning UoW enter, rollback, commit, outcome, and exit.
- Outcome-preserving command finalization errors.

## Invocation Invariants

- Only decorated command handlers receive automatic transactions.
- Applying the decorator to a query/event handler fails before startup.
- Transaction binding uses the outer/system interceptor phase and wraps graph and
  normal handler interceptors.
- Factory-produced handlers require interceptor metadata on their explicit CQRS
  binding through command-constrained `event_sourcing_transaction(key=...)`.
- The transaction coordinator/UoW enters before handler construction and exits
  after handler-scoped resources.
- Exactly one UoW is created and entered for one invocation.
- Handler success triggers exactly one commit, including no-op commands.
- The exact handler result is retained and returned only after successful commit
  and scope finalization.
- Provider or handler failure before commit triggers explicit rollback.
- A handler never receives commit/rollback methods from the integration API.
- Manual commit from an integration-managed transaction is unsupported and fails
  rather than being silently accepted.

## Outcome Invariants

- Optimistic conflicts, duplicate IDs, confirmed store rejection, and
  adapter-confirmed rollback cancellation are confirmed non-commits.
- Explicit indeterminate errors, malformed commit results, ambiguous
  cancellation, and unknown post-commit-start failures are indeterminate.
- Aggregate fault/release behavior remains owned by `tori-py-cqrs-event-sourcing-core`.
- Commit failure prevents the retained handler result from escaping.
- Cleanup after confirmed commit raises an error carrying `CommitResult`, handler
  result, phase, cause, and secondary cleanup failures.
- Original event-sourcing errors pass through unchanged when no secondary
  finalization failure requires wrapping.

## Tests

- Create/reload and multi-aggregate atomic commit.
- Exact result identity and response after confirmed commit.
- No-op command and empty `CommitResult`.
- Constructor/provider failure, handler exception, and handler control flow.
- Optimistic conflict and duplicate event identity.
- Confirmed rejection, raw known-rollback cancellation, ambiguous cancellation,
  explicit indeterminate failure, unknown failure, and malformed result.
- Commit success followed by handler dependency, transaction, or UoW cleanup
  failure.
- Concurrent commands have isolated UoWs and repository instances.
- Escaped repositories and child-task operations fail transaction lease checks.
- Query, event, and undecorated command invocation create no automatic UoW.

## Exit Criteria

- Command handlers contain no explicit UoW or commit plumbing while all ES4
  transaction guarantees remain observable.
