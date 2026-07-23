# CQRS Event Sourcing Specifications

This directory governs the implemented optional `cqrs-event-sourcing`
distribution.
The architecture and implementation order are recorded in
[`CQRS_EVENT_SOURCING_IMPLEMENTATION_PLAN.md`](../../CQRS_EVENT_SOURCING_IMPLEMENTATION_PLAN.md).

The event-sourcing package depends on `cqrs-core` without changing the completed
first CQRS slice. It is framework-neutral, persistence-adapter-neutral, and has
Python standard library runtime dependencies only beyond `cqrs-core`.

## Phase Map

| Phase | Main result |
| --- | --- |
| ES0 | [Workspace boundary, public package contract, and artifact checks](phase-es0-workspace-and-contracts.md) |
| ES1 | [Immutable event records and deterministic `AggregateRoot` semantics](phase-es1-aggregate-and-records.md) |
| ES2 | [Stable event schemas, codecs, and contiguous upcasting](phase-es2-schemas-and-codecs.md) |
| ES3 | [Transactional EventStore protocol and in-memory reference store](phase-es3-event-store.md) |
| ES4 | [Event-sourced repository and explicit Unit of Work](phase-es4-repository-and-uow.md) |
| ES5 | [Acceptance flow, artifact verification, review, and hardening](phase-es5-acceptance-and-hardening.md) |
| ES6 | [Typed UoW outcomes and repository operation leases](phase-es6-outcomes-and-leases.md) |

Detailed phase files must be written before implementation of each phase. Every
phase file defines entry criteria, deliverables, invariants, typed failure
behavior, tests, and exit criteria. Do not resolve a missing contract silently in
code.

## Cross-Phase Invariants

1. Distribution name is `cqrs-event-sourcing`; import name is
   `cqrs_event_sourcing`.
2. Dependency direction is `cqrs-event-sourcing -> cqrs-core` with no reverse
   import.
3. Aggregate behavior and event application are synchronous and perform no I/O.
4. Persistence protocols are asynchronous and use explicit transaction
   ownership.
5. Missing streams have version 0; committed stream versions and global
   positions start at 1 and remain contiguous/monotonic as applicable.
6. Every append uses an exact expected version and commits atomically.
7. One transaction accepts at most one finite append batch per stream.
8. Replay never records pending events or publishes messages; any event-applier
   exception faults the aggregate.
9. Saving exclusively enlists an aggregate; repeated save and duplicate aggregate
   instances for one stream are rejected within a Unit of Work.
10. Pending events clear only after a confirmed storage commit and a prevalidated,
   non-failing local state transition.
11. Concurrency and duplicate-event conflicts fault stale aggregate instances
    and require reload rather than reuse.
12. An indeterminate durable commit outcome faults local aggregate instances and
    requires store reconciliation rather than blind retry.
13. Raw cancellation means confirmed rollback; ambiguous adapter cancellation is
    reported as `IndeterminateCommitError`.
14. Transactions and Units of Work enter `COMMITTING` before their first commit
    await and reject competing lifecycle or mutation operations.
15. Cleanup failure after confirmed commit preserves that fact in a typed error
    carrying the `CommitResult`.
16. Transactional stream reads use finite pagination over one repeatable
    committed snapshot and do not expose staged appends.
17. Persisted event aliases and schema versions are stable explicit contracts,
    not Python class paths.
18. Schema registration is explicit and frozen before use; there is no package
    scanning or process-global registry.
19. `EventBus` delivery and EventStore persistence remain separate concerns.
20. The in-memory store is a semantic reference and never claims durability.
21. PostgreSQL, outbox delivery, durable projectors, and Citus require separate
    adapter specifications.
22. Every dependency, test, build, and quality command runs through `uv`.

## Change Control

1. Update the relevant ES phase specification before changing agreed behavior.
2. Update the root implementation plan when phase order, package scope, or
   non-goals change.
3. Add or update tests that demonstrate the behavior.
4. Update `AGENTS.md` only for durable repository-wide guidance.
