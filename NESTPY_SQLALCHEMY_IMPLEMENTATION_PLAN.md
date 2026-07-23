# Nestpy SQLAlchemy Implementation Plan

## Status

Implementation status: completed.

Architecture: [`NESTPY_SQLALCHEMY_ARCHITECTURE.md`](NESTPY_SQLALCHEMY_ARCHITECTURE.md).

## Delivery Order

### NS0: Workspace and Contracts

- Add `packages/nestpy-sqlalchemy` as a uv workspace member.
- Depend only on `nestpy` and `sqlalchemy[asyncio]` at runtime.
- Add `README.md`, `py.typed`, exact `__all__`, and import-boundary tests.
- Add immutable options, public errors, and deterministic keyed tokens.

### NS1: Dynamic Modules

- Implement `SqlAlchemyModule.for_root()` for module-owned engines.
- Implement `SqlAlchemyModule.for_root_async()` with an annotation-driven Nestpy
  `FactoryProvider`; do not invoke or wrap the user factory at materialization.
- Implement `SqlAlchemyModule.for_engine()` for externally owned engines.
- Export unqualified `AsyncEngine` and `AsyncSession` aliases only for the
  `default` root.

### NS2: Lifecycle and Scopes

- Create owned engines lazily during singleton startup.
- Dispose owned engines exactly once during shutdown or startup rollback.
- Register one singleton `async_sessionmaker` per root.
- Register one managed request-scoped `AsyncSession` per HTTP/work scope.
- Preserve native SQLAlchemy transaction semantics without implicit begin,
  commit, or rollback policy beyond session close.

### NS3: Verification

- Verify options immutability and configuration diagnostics.
- Verify sync and async DI-resolved options factories.
- Verify direct and token-backed external engine ownership.
- Verify default aliases, non-default keyed isolation, and dynamic descriptor
  reuse requirements.
- Verify same-scope session identity, cross-scope isolation, exact cleanup, and
  engine disposal.
- Verify startup failure unwinds an already acquired owned engine.
- Verify public import boundaries and package artifacts.

### NS4: Acceptance

- Run package and Nestpy regression tests through uv.
- Run Ruff lint and formatting checks.
- Run ty against the new package and existing configured package paths.
- Build the distribution and inspect the wheel/sdist contents.
- Complete an independent code-quality review and resolve findings.

## Deferred Work

- Alembic scaffolding or CLI integration.
- Database health checks.
- OpenTelemetry SQL instrumentation helpers.
- Tenant and replica routing.
- Testing API changes for scope-preserving provider overrides.
- Any transaction, CQRS, event-sourcing, outbox, or broker integration.
