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
- Export unqualified `AsyncEngine`, `SessionManager`, and `EntityManager` aliases
  only for the `default` root.

### NS2: Lifecycle and Managers

- Create owned engines lazily during singleton startup.
- Dispose owned engines exactly once during shutdown or startup rollback.
- Register one singleton `async_sessionmaker` per root.
- Register singleton `SessionManager` and `EntityManager` providers per root.
- Open sessions only inside explicit manager session/transaction contexts.
- Add transaction-bound SQLAlchemy-native entity operations.
- Add one-shot entity operations with automatic commit/rollback/close.

### NS3: Verification

- Verify options immutability and configuration diagnostics.
- Verify sync and async DI-resolved options factories.
- Verify direct and token-backed external engine ownership.
- Verify default aliases, non-default keyed isolation, and dynamic descriptor
  reuse requirements.
- Verify singleton manager identity, concurrent session isolation, exact cleanup,
  detached values, rollback, and engine disposal.
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
- Read-only transaction policy and streaming manager contexts.
- CQRS, event-sourcing, outbox, or broker integration.
