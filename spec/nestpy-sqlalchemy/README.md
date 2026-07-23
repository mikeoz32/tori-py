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
8. One session factory exists per configured root.
9. One managed session exists per Nestpy request/work scope.
10. The integration never begins, commits, or rolls back a business transaction
    automatically.
11. Application services use native `AsyncSession.begin()` boundaries.
12. Models, metadata, repositories, migrations, and DDL belong to the
    application.
13. There is no CQRS, event-sourcing, outbox, broker, or HTTP middleware API.
14. Every dependency, test, build, and quality command uses uv.

## Change Control

Update the architecture and this invariant list before changing package
ownership, scope, transaction, or public API semantics. Every behavior change
requires a focused executable test.
