# ES5: Acceptance and Hardening

## Entry Criteria

- ES0-ES4 exit criteria pass.

## Deliverables

- In-memory profile aggregate acceptance flow.
- Public API inventory and package-level documentation.
- Isolated wheel and source artifact smoke script.
- Final multi-axis review and full repository verification.

## Invariants

- Aggregate state rebuilds exclusively from committed events.
- Concurrent stale writers fail through optimistic concurrency.
- Global reads expose committed events without implying durable projection
  checkpoints.
- Artifact use requires only `tori-py-cqrs-core` and the standard library.
- Documentation does not claim durable storage, automatic publication,
  exactly-once commands, outbox delivery, or production projection recovery.

## Failure Behavior

- Any public API, artifact, import-boundary, typing, formatting, or behavioral
  regression blocks completion.

## Tests

- Profile create and rename flow, equivalent replayed state, ordered event feed,
  and concurrency conflict.
- Wheel and source distribution smoke tests with local `tori-py-cqrs-core` artifacts.
- Complete pytest, Ruff, formatter, ty, lock, and strict documentation gates.

## Exit Criteria

- Independent review has no required findings.
- All focused, artifact, and repository-wide gates pass.
