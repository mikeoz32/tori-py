# ES1: Aggregate and Event Records

## Entry Criteria

- ES0 exit criteria pass.

## Deliverables

- Validated immutable stream IDs, event metadata, pending events, and recorded
  events.
- Generic `AggregateRoot` with recording, finite-page replay, fault, enlistment,
  release, and confirmed-commit transitions.
- Typed value and aggregate lifecycle errors.

## Invariants

- Missing streams have version 0; committed event versions begin at 1.
- Event metadata is validated before aggregate state application.
- Every `_apply()` exception faults the aggregate.
- Replay never records pending events and accepts only contiguous versions from
  one stream.
- Enlisted aggregates reject mutation and second enlistment.
- Only the owning Unit of Work token can release or commit an enlisted aggregate.
- Confirmed commit clears exactly the prevalidated pending snapshot.

## Failure Behavior

- Invalid IDs, timestamps, UUIDs, headers, versions, and events raise typed value
  errors without mutation.
- Replay gaps, mixed streams, invalid lifecycle transitions, and commit-state
  mismatches raise typed aggregate errors.
- Faulted aggregates remain inspectable but cannot be reused.

## Tests

- Record ordering, metadata defaults, explicit metadata, and immutability.
- Replay purity across multiple pages and rejection of gaps/mixed streams.
- Apply failures fault both live and replayed aggregates.
- Enlist/release ownership and exact commit clearing.

## Exit Criteria

- ES1 tests pass without store, framework, or serializer dependencies.
