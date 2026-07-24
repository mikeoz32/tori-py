# Nestpy SQLAlchemy Specifications

The optional `nestpy-sqlalchemy` distribution integrates Nestpy lifecycle and
DI scopes with SQLAlchemy's asynchronous engine and session APIs. Its
architecture and implementation order are recorded in:

- [`NESTPY_SQLALCHEMY_ARCHITECTURE.md`](../../NESTPY_SQLALCHEMY_ARCHITECTURE.md)
- [`NESTPY_SQLALCHEMY_IMPLEMENTATION_PLAN.md`](../../NESTPY_SQLALCHEMY_IMPLEMENTATION_PLAN.md)

## Invariants

1. Distribution name is `nestpy-sqlalchemy`; import name is
   `nestpy_sqlalchemy`.
2. `nestpy` has no reverse dependency on SQLAlchemy or this integration.
3. Runtime dependencies are limited to Nestpy and SQLAlchemy.
4. Database drivers and Alembic remain application dependencies.
5. `for_root()` owns and disposes the engine it creates.
6. `for_engine()` never disposes the external engine it receives.
7. `for_root_async()` resolves one sync-or-async options factory through normal
   annotation-based Nestpy DI.
8. One session factory, SessionManager, and EntityManager exist per root; roots
   are global by default and remain deterministically keyed.
9. Every session is created locally by a manager call and always closed.
10. Managers are singleton and never retain current session or transaction state.
11. One-shot EntityManager writes commit automatically and roll back on failure.
12. Atomic multi-operation work uses one explicit bound EntityTransaction.
13. Bound transactions expose no commit, rollback, or close control.
14. Explicit feature registration provides default model-bound repositories and
    decorated custom repository classes without scanning or generated classes.
15. Repository criteria are native SQLAlchemy expressions, not a custom query
    language.
16. Repository transaction binding is explicit, preserves the concrete class,
    and rejects inactive or wrong-root transactions.
17. Models, metadata, migrations, and application query policy remain
    application-owned.
18. There is no model scan, generated repository class, CQRS, event-sourcing,
    outbox, broker, or HTTP middleware API.
19. Every dependency, test, build, and quality command uses uv.

## Change Control

Update the architecture and this invariant list before changing package
ownership, scope, transaction, or public API semantics. Every behavior change
requires a focused executable test.
