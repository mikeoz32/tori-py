# Nestpy SQLAlchemy Architecture

## 1. Status and Scope

This document defines the `nestpy-sqlalchemy` integration. The distribution
connects Nestpy singleton lifecycle and dependency injection to SQLAlchemy's
asynchronous engine, session factory, and ORM entity APIs.

The integration owns:

- creation and deterministic disposal of module-owned `AsyncEngine` values;
- registration of externally owned engines without taking ownership;
- one singleton `async_sessionmaker` per configured root;
- one singleton `SessionManager` per root;
- one singleton `EntityManager` per root;
- short-lived sessions and transactions opened by those managers;
- SQLAlchemy-native, generic entity operations without model registration;
- synchronous and DI-resolved asynchronous root configuration;
- deterministic keyed tokens for multiple database roots.

The integration does not own:

- request-scoped sessions or ambient/current-session propagation;
- CQRS, event sourcing, outbox, inbox, retries, or message handling;
- ORM model scanning, generated repositories, or a custom query language;
- migrations, `MetaData.create_all()`, or startup schema mutation;
- tenant routing, replica routing, sharding, or distributed transactions;
- database-driver installation or database-specific behavior.

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

`nestpy` MUST NOT import SQLAlchemy or this integration. The integration MUST
NOT import CQRS, event-sourcing, HTTP-driver, broker, serializer, migration, or
database-driver packages.

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

Sensitive URL and engine options are excluded from representations.
`engine_options` is defensively copied and passed to `create_async_engine()`.
The session defaults keep all transaction starts explicit.

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

`for_root()` owns its engine. `for_engine()` never disposes its external engine.
`for_root_async()` registers its sync-or-async `use_factory` directly as a
singleton Nestpy provider. Factory dependencies use annotations and
`Annotated[..., Inject(token)]`; no separate `inject=[]` API exists.

## 5. Providers and Tokens

Every root has canonical qualified singleton providers:

```text
nestpy_sqlalchemy:<key>:engine
nestpy_sqlalchemy:<key>:session_factory
nestpy_sqlalchemy:<key>:session_manager
nestpy_sqlalchemy:<key>:entity_manager
```

For `key="default"`, `AsyncEngine`, `SessionManager`, and `EntityManager` are
additional aliases. Named roots expose only qualified tokens:

```python
get_engine_token(key="analytics")
get_session_factory_token(key="analytics")
get_session_manager_token(key="analytics")
get_entity_manager_token(key="analytics")
```

There is no `AsyncSession` provider or `get_session_token()`. Application
singletons therefore cannot accidentally retain operation state.

## 6. SessionManager

`SessionManager` stores only the singleton session factory:

```python
class SessionManager:
    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...
    def transaction(self) -> AbstractAsyncContextManager[AsyncSession]: ...
```

`session()` opens and always closes one session but starts no transaction.
Because `autobegin=False`, SQL work in that context still requires an explicit
`session.begin()`.

`transaction()` nests a transaction context inside a session context. It opens a
new session, begins a transaction, commits on success, rolls back on failure,
and always closes the session, including when commit or rollback itself fails.

The singleton stores no current session and uses no `ContextVar`. Concurrent
calls always receive separate sessions.

## 7. EntityTransaction

`EntityManager.transaction()` yields an `EntityTransaction` bound to exactly one
manager-owned session and transaction:

```python
async with entities.transaction() as transaction:
    member = await transaction.get_one(MemberRow, member_id)
    transaction.add(AuditRow(member_id=member.id, action="updated"))
    await transaction.flush()
```

The transaction exposes SQLAlchemy-native operations:

- `add()` and `add_all()`;
- `get()` and `get_one()`;
- `merge()` and `delete()`;
- `flush()` and `refresh()`;
- buffered `execute()`, `scalar()`, and `scalars()`.

It does not expose `commit()`, `rollback()`, or `close()`. The surrounding
context owns finalization. It also does not expose streaming results because
they could escape the session lifetime.

One bound `EntityTransaction` or low-level `AsyncSession` belongs to one task.
It MUST NOT be shared across concurrent tasks or used concurrently through
`asyncio.gather()`; concurrency safety applies to independent manager calls,
which create separate sessions.

## 8. EntityManager

`EntityManager` is a singleton generic gateway. Every one-shot call creates a
fresh transaction through `SessionManager`, delegates to `EntityTransaction`,
then commits or rolls back and closes automatically:

```python
member = await entities.get(MemberRow, member_id)
created = await entities.add(MemberRow(name="Ada"))
rows = await entities.scalars(select(MemberRow).order_by(MemberRow.id))
```

One-shot write methods `add()`, `add_all()`, `merge()`, `delete()`, and
`execute()` commit automatically. Read methods also execute inside an explicit
transaction because `autobegin=False`.

One-shot ORM entities are detached after the method returns. With the default
`expire_on_commit=False`, loaded scalar attributes remain available; required
relationships MUST be loaded explicitly through SQLAlchemy loader options.
Applications that opt into `expire_on_commit=True` also opt out of usable
detached return values because loaded attributes may be expired at commit.
Applications use `merge()` for detached changes.

Multiple one-shot calls are independent transactions. Atomic composition MUST
use one explicit `EntityManager.transaction()` and its bound manager. There is
no implicit transaction propagation to nested services or child tasks.
Locked reads and all work that depends on them MUST remain inside that same
bound transaction; a one-shot `execute()` releases database locks before it
returns.

## 9. Application Providers

Stateless repositories, services, and controllers SHOULD be singleton providers:

```python
@injectable()
class MemberService:
    def __init__(self, entities: EntityManager) -> None:
        self._entities = entities
```

Application-specific repositories remain valid when they express reusable query
or persistence policy, but they are not generated by this integration. Trivial
pass-through repositories SHOULD be omitted in favor of `EntityManager`.

## 10. Models and Migrations

The application owns `DeclarativeBase`, mappings, metadata, repository policy,
and migrations. There is no `for_feature()`, entity decorator, model scan,
process-global registry, or TypeORM-like criteria language.

Complex queries remain normal SQLAlchemy statements. Alembic remains a separate
deployment tool, and the integration performs no DDL during startup.

## 11. Testing

Contract tests MUST verify:

- managers are singleton and create no session during startup;
- each concurrent manager call receives a distinct session;
- success commits and closes exactly once;
- failure rolls back and closes exactly once;
- bound operations share one identity map and transaction;
- one-shot operations return usable detached values;
- keyed roots resolve distinct managers;
- owned and external engine disposal semantics;
- real async-driver add/get/query/update/delete and rollback behavior;
- public API, import boundaries, type marker, wheel, and sdist artifacts.

## 12. Non-Goals

The distribution does not add HTTP middleware, CQRS, event sourcing, outbox,
retries, model discovery, generated repositories, custom query builders,
automatic migrations, health checks, tenant engine caches, read/write splitting,
two-phase commit, or database-driver-specific APIs.
