# PS4: Acceptance and Release

Status: implemented.

## Entry Criteria

- PS0-PS3 exit criteria pass.
- The in-memory reference passes the complete reusable conformance suite.

## Deliverables

- Multi-partition, multi-owner in-memory acceptance scenario.
- Acceptance coverage for both checkpoint strategies and every start mode.
- Explicit demonstration of at-least-once redelivery and the external
  checkpoint/side-effect non-atomic window.
- Public API inventory and package-level documentation.
- Isolated wheel and source-distribution smoke flow.
- Final architecture, correctness, concurrency, typing, and security review.

## Invariants

- Acceptance claims partition-local ordering only.
- A named-producer retry resolves to one accepted publication receipt without implying
  exactly-once consumption.
- Checkpoint always follows successful processing.
- Poison failure stops its partition without skipping the record.
- Retention gaps are typed and require an explicit application recovery choice.
- The artifact requires only Python 3.14 and the standard library at runtime.
- Documentation does not claim durability, automatic retry, global ordering,
  dead letters, atomic side effects, or a production broker adapter.

## Failure Behavior

- Any conformance, acceptance, public API, artifact, dependency-boundary,
  typing, formatting, or documentation regression blocks completion.
- A test that relies on cross-partition timing or treats an empty read as final
  is invalid and must be corrected rather than stabilized by implementation
  coupling.

## Tests

- Three-or-more-partition routing and ordered opaque record consumption.
- Two owners with exclusive assignment, poison stop, unaffected partition
  progress, reacquisition, and same-record redelivery.
- Broker-managed and external checkpoint restart flows.
- Side effect followed by failed external checkpoint proving possible duplicate
  effect on redelivery.
- Beginning, end, exact-offset, timestamp, and relative-time starts with existing
  checkpoint precedence.
- Controlled trim followed by exact-offset and stale-checkpoint
  `RetentionGapError`.
- Named producer exact retry and publishing conflict.
- Wheel and source artifacts installed and exercised in isolated `uv`
  environments.
- Focused pytest, full pytest, Ruff, formatter, ty, and documentation gates.

## Exit Criteria

- Independent review has no required findings.
- Focused, conformance, acceptance, artifact, and repository-wide gates pass.
- Remaining production-adapter work is explicitly documented as follow-up and
  not represented as implemented behavior.
