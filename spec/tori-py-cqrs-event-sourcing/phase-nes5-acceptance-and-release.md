# NES5: Acceptance and Release

## Entry Criteria

- NES0-NES4 pass.

## Deliverables

- Large community example migrated to `tori-py-cqrs-event-sourcing`.
- No command handler injects `EventSourcingUnitOfWork` or calls `commit()`.
- Member, group, and post repositories are decorated repository classes.
- ContentVault compensation uses `CommandSynchronization`.
- Documentation for module composition, transactions, cancellation, and outbox
  boundaries.
- Independent code review and release artifacts.

## Acceptance Flow

The existing community behavior remains unchanged:

- bearer identity becomes an explicit trusted actor ID in commands;
- member registration and historical event upcasting work;
- private membership and roster privacy are enforced;
- posting requires active membership;
- moderation and suspension are enforced;
- content bodies remain outside immutable events;
- projection catch-up fails closed and listing remains bounded;
- stale writers fail optimistic concurrency;
- confirmed rollback compensates content while indeterminate outcomes retain it
  for reconciliation.

The application composition changes from manual request-scoped UoW wiring to:

- one root event-sourcing dynamic module;
- one feature module listing decorated repository classes;
- `@use_event_sourcing()` on command handlers;
- repository injection through
  `Annotated[Repo, aggregate_repository(Repo)]`;
- synchronization callbacks for external content.

## Release Verification

- Focused tests for every NES phase.
- Full workspace pytest.
- Ruff check and format check.
- Full configured `ty` paths including the new package and examples.
- Strict MkDocs build.
- Lockfile and diff checks.
- Wheel and source-distribution build.
- Isolated install/import and minimal transactional-command smoke test from both
  artifacts.
- Dependency inspection proving no HTTP, ORM, database-driver, or broker leak.
- Independent correctness, architecture, security, and performance review.

## Residual Risks to Document

- Caller timeout does not prove command cancellation.
- Commands are not automatically idempotent.
- In-process callbacks and EventBus publication are not durable.
- External resources are not atomically coordinated without a shared adapter or
  outbox.
- Nested commands do not share transactions.
- Durable store isolation, reconciliation, and outbox semantics belong to their
  adapter specifications.

## Exit Criteria

- The example is materially simpler and more ToriPy-native than manual UoW
  injection without hiding any persistence outcome.
- Full quality and artifact gates pass.
- Independent review has no required findings.
