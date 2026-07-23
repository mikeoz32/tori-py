# Nestpy SQLAlchemy Architecture

## 1. Status and Scope

This document defines the first `nestpy-sqlalchemy` integration slice. The
distribution connects Nestpy dependency-injection scopes and application
lifecycle to SQLAlchemy's asynchronous engine and session APIs.

The integration owns only:

- creation and deterministic disposal of module-owned `AsyncEngine` values;
- registration of application-owned external engines without taking ownership;
- one singleton `async_sessionmaker` per configured database root;
- one managed `AsyncSession` per Nestpy request or work scope;
- synchronous and DI-resolved asynchronous root configuration;
- deterministic keyed tokens for multiple database roots.

The integration does not own:

- transaction boundaries, automatic commit, or transaction-per-request policy;
- CQRS, event sourcing, outbox, inbox, retries, or message handling;
- ORM model or repository registration, scanning, or generation;
- migrations, `MetaData.create_all()`, or startup schema mutation;
- tenant routing, replica routing, sharding, or distributed transactions;
- database-driver installation or database-specific behavior.

Applications use native SQLAlchemy transaction APIs, normally
`async with session.begin()`, in an application service that defines one
business operation.

## 2. Package Boundary

```text
nestpy-sqlalchemy
  -> nestpy
  -> sqlalchemy[asyncio]

application
  -> nestpy-sqlalchemy
  -> an async SQLAlchemy driver
  -> Alembic when migrations are required
```

`nestpy` MUST NOT import `nestpy_sqlalchemy` or SQLAlchemy. The integration MUST
NOT import CQRS, event-sourcing, HTTP-driver, broker, serializer, or migration
packages. A database driver remains an application dependency selected by the
SQLAlchemy URL.

## 3. Public Configuration

```python
@dataclass(frozen=True, slots=True)
class SqlAlchemySessionOptions:
    expire_on_commit: bool = False
    autoflush: bool = False
    autobegin: bool = False


@dataclass(frozen=True, slots=True)
class SqlAlchemyOptions:
    url: str | URL
    engine_options: Mapping[str, object] = MappingProxyType({})
    session: SqlAlchemySessionOptions = SqlAlchemySessionOptions()
```

`engine_options` is defensively copied and exposed as an immutable mapping. It
is passed to `create_async_engine()` without reproducing SQLAlchemy's option
surface in Nestpy. The integration rejects an option named `url`, because the
URL is supplied separately.

The session defaults deliberately set `autobegin=False`. Database access must
therefore occur inside an explicit SQLAlchemy transaction. The integration does
not catch or replace SQLAlchemy's native error when application code violates
that rule.

## 4. Dynamic Module API

```python
class SqlAlchemyModule:
    @classmethod
    def for_root(
        cls,
        options: SqlAlchemyOptions,
        *,
        key: str = "default",
        global_: bool = False,
    ) -> DeferredModule: ...

    @classmethod
    def for_root_async(
        cls,
        *,
        use_factory: SqlAlchemyOptionsFactory,
        imports: Iterable[ModuleImport] = (),
        key: str = "default",
        global_: bool = False,
    ) -> DeferredModule: ...

    @classmethod
    def for_engine(
        cls,
        engine: AsyncEngine | Token,
        *,
        session: SqlAlchemySessionOptions = SqlAlchemySessionOptions(),
        imports: Iterable[ModuleImport] = (),
        key: str = "default",
        global_: bool = False,
    ) -> DeferredModule: ...
```

`for_root()` receives final immutable options. `for_root_async()` means that the
options are resolved through Nestpy DI; the method itself is synchronous and
returns a `DeferredModule`. Its `use_factory` may be synchronous or asynchronous
and runs exactly once as a singleton provider during application startup.

Dependencies of `use_factory` are declared through Python annotations and
`Annotated[..., Inject(token)]`. There is no separate NestJS-style `inject=[]`
argument. The factory MUST return `SqlAlchemyOptions`; otherwise startup fails
with `SqlAlchemyConfigurationError`.

`for_engine()` registers either a direct `AsyncEngine` value or an imported
engine token. Such an engine is externally owned and is never disposed by this
module.

## 5. Providers and Ownership

Each root has these canonical keyed providers:

```text
nestpy_sqlalchemy:<key>:engine          singleton managed when module-owned
nestpy_sqlalchemy:<key>:session_factory singleton unmanaged
nestpy_sqlalchemy:<key>:session         request scoped and managed
```

For `key="default"`, `AsyncEngine` and `AsyncSession` are additional aliases to
the keyed canonical providers. Non-default roots expose only keyed tokens, so
multiple roots cannot create unqualified ambiguity accidentally.

An engine created by `for_root()` is wrapped in a managed async context manager.
The resource is yielded after `create_async_engine()` succeeds and
`await engine.dispose()` runs exactly once when the application resource stack
closes, including startup rollback.

The session factory is a singleton value. A request-scoped provider calls it and
enters the resulting `AsyncSession` as an async context manager. The same scope
returns the same session; different HTTP request or explicit work scopes receive
different sessions. Scope cleanup closes the session and rolls back any active,
uncommitted transaction according to SQLAlchemy semantics.

## 6. Application Transaction Boundary

The integration exposes raw `AsyncSession`, not a wrapper or custom Unit of Work:

```python
class CreateMemberService:
    def __init__(self, session: AsyncSession, members: MemberRepository) -> None:
        self._session = session
        self._members = members

    async def execute(self, data: CreateMemberData) -> Member:
        async with self._session.begin():
            member = Member.create(data)
            await self._members.add(member)
            await self._session.flush()
            return member
```

Repositories MAY add, execute, query, and flush. Repositories MUST NOT own
`commit()`, `rollback()`, or `close()`. Nested savepoints use native
`session.begin_nested()` explicitly. One `AsyncSession` MUST NOT be used
concurrently by multiple tasks.

## 7. Models and Migrations

The application owns `DeclarativeBase`, mappings, metadata, and repositories.
There is no `for_feature()`, entity decorator, generic CRUD repository, model
scan, or process-global registry.

Alembic remains a deployment tool. The integration performs no DDL at startup.
Migration code imports application-owned metadata and is run separately through
`uv run alembic ...`.

## 8. Testing

`for_engine()` permits tests to provide an externally owned engine. Keyed engine
and session-factory tokens are exported for normal Nestpy testing overrides.
Request-scoped session replacement should use module replacement or an alias to
another request-scoped provider, because the current generic
`TestingModule.use_factory()` override creates a singleton declaration.

Unit tests use deterministic fake engine/session resources to prove DI and
ownership. Database-specific application tests use a real database container;
SQLite does not prove PostgreSQL isolation, locking, or constraint behavior.

## 9. Public Errors

The integration owns only configuration errors:

```text
SqlAlchemyIntegrationError
SqlAlchemyConfigurationError
```

SQL execution and transaction failures remain native SQLAlchemy exceptions.
Nestpy scope and lifecycle failures remain native Nestpy exceptions.

## 10. Non-Goals

The first distribution MUST NOT add automatic transactions, HTTP middleware,
method interception, health-check abstractions, telemetry, caching, brokers,
CQRS, event sourcing, outbox behavior, migration execution, tenant engine
caches, read/write splitting, two-phase commit, or driver-specific APIs.
