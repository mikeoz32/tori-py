# Nestpy CQRS Event-Sourcing Specifications

This directory specifies the implemented optional `nestpy-cqrs-event-sourcing`
distribution. The architecture is recorded in
[`NESTPY_CQRS_EVENT_SOURCING_ARCHITECTURE.md`](../../NESTPY_CQRS_EVENT_SOURCING_ARCHITECTURE.md).

The integration consumes public Nestpy, `nestpy-cqrs`, `cqrs-core`, and
`cqrs-event-sourcing` contracts without creating reverse dependencies.

## Terms

- **MUST**: required for the first integration slice.
- **MUST NOT**: prohibited for the first integration slice.
- **SHOULD**: the default unless an implementation constraint is documented.
- **MAY**: optional and cannot weaken a required guarantee.

## Phase Map

| Phase | Specification | Depends on | Main result |
| --- | --- | --- | --- |
| NES0 | [Workspace and public contracts](phase-nes0-workspace-and-contracts.md) | Implemented Nestpy, CQRS, and event sourcing | Package boundary and frozen public API |
| NES1 | [Invocation and resource foundation](phase-nes1-invocation-and-resources.md) | NES0, N8, C3, ES6, CQRS7 | Integration over completed upstream foundations |
| NES2 | [Dynamic modules and repositories](phase-nes2-modules-and-repositories.md) | NES0-NES1 | Keyed root/feature modules and decorated repositories |
| NES3 | [Transactional commands](phase-nes3-transactional-commands.md) | NES0-NES2 | Automatic commit and exact outcome handling |
| NES4 | [Synchronization and hardening](phase-nes4-synchronization-and-hardening.md) | NES0-NES3 | Side-effect callbacks, cancellation, nesting, cleanup |
| NES5 | [Acceptance and release](phase-nes5-acceptance-and-release.md) | NES0-NES4 | Migrated example and artifact verification |

## Cross-Phase Invariants

1. Distribution name is `nestpy-cqrs-event-sourcing`; import name is
   `nestpy_cqrs_event_sourcing`.
2. Dependency direction is integration package to framework/core packages only;
   no dependency imports the integration package.
3. The integration has no HTTP-driver, ORM, database-driver, broker, serializer,
   or DI dependency beyond Nestpy itself.
4. Modules, repositories, schemas, handlers, and interceptors are registered
   explicitly; there is no package scan or process-global registry.
5. Domain aggregates do not import Nestpy integration decorators.
6. Repository classes are explicit `EventSourcedRepository` subclasses decorated
   with `@aggregate_repository(Aggregate, category=...)` and registered through
   `for_feature()`.
7. `aggregate_repository(RepositoryClass)` used in `Annotated` returns the normal
   Nestpy injection marker for that repository token.
8. One decorated command invocation owns one fresh UoW and transaction; queries,
   events, and undecorated commands own none automatically.
9. Handlers never receive commit or rollback control from this package.
10. A command result becomes observable only after confirmed commit,
    synchronization, and work-scope finalization.
11. Confirmed commit, confirmed non-commit, and indeterminate outcomes are never
    collapsed into one generic failure.
12. Caller cancellation is not handler cancellation and is not rollback proof.
13. EventStore persistence and EventBus publication remain separate.
14. Nested same-bus command dispatch is rejected before enqueue and never shares
    an outer UoW.
15. Dynamic modules follow exact Nestpy identity, visibility, scope, lifecycle,
    and testing-override semantics.
16. Root modules are globally visible keyed infrastructure imported once at
    application composition; feature modules select them by `root_key`, never by
    receiving or importing a root descriptor.
17. Feature modules create and export repositories only. Every `for_feature()`
    call owns a fresh private module identity, so independent submodules may
    register identical repository sets without descriptor coupling.
18. Every dependency, test, build, and quality command uses `uv`.

## Change Control

1. Update the architecture document when a package boundary or lifecycle decision
   changes.
2. Update the affected NES phase before implementing changed behavior.
3. Update upstream Nestpy, CQRS, or event-sourcing specifications when their
   public contracts change.
4. Add behavioral tests proving every changed invariant.
5. Do not silently choose behavior for an unresolved transaction outcome.
