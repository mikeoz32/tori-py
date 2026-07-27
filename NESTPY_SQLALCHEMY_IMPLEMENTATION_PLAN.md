# Nestpy SQLAlchemy Implementation Plan

## Status

Implementation status: completed through guarded ambient transactions.

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
- Export unqualified `AsyncEngine` and `EntityManager` aliases
  only for the `default` root.

### NS2: Lifecycle and Managers

- Create owned engines lazily during singleton startup.
- Dispose owned engines exactly once during shutdown or startup rollback.
- Register one singleton `async_sessionmaker` per root.
- Register one singleton `EntityManager` per root directly over the session factory.
- Require lexical manager transactions for every entity/repository operation.
- Propagate current state only through an instance ContextVar with owner-task guards.
- Use native savepoints for same-task nested scopes.

### NS3: Verification

- Verify options immutability and configuration diagnostics.
- Verify sync and async DI-resolved options factories.
- Verify direct and token-backed external engine ownership.
- Verify default aliases, non-default keyed isolation, and dynamic descriptor
  reuse requirements.
- Verify same singleton yield, concurrent session isolation, savepoints,
  child-task rejection, exact cleanup, detached values, and engine disposal.
- Verify startup failure unwinds an already acquired owned engine.
- Verify public import boundaries and package artifacts.

### NS4: Acceptance

- Run package and Nestpy regression tests through uv.
- Run Ruff lint and formatting checks.
- Run ty against the new package and existing configured package paths.
- Build the distribution and inspect the wheel/sdist contents.
- Complete an independent code-quality review and resolve findings.

### NS5: Repositories

- Make keyed SQLAlchemy roots global by default while preserving explicit
  `global_=False` opt-out.
- Add model-bound default `Repository` CRUD and native-expression query helpers.
- Add explicit custom `@repository(Entity)` declarations with no scanning or
  generated classes.
- Add deterministic repository tokens, `inject_repository()`, and
  `SqlAlchemyModule.for_feature()` over global keyed managers.
- Make repositories use their keyed manager's active contextual transaction;
  remove binding, cloning, one-shot execution, and transaction arguments.
- Verify default/custom DI, named roots, detached values, rich queries,
  transaction rollback, context errors, and exact public artifacts.

## Deferred Work

- Alembic scaffolding or CLI integration.
- Database health checks.
- OpenTelemetry SQL instrumentation helpers.
- Tenant and replica routing.
- Read-only transaction policy and streaming manager contexts.
- CQRS, event-sourcing, outbox, or broker integration.
