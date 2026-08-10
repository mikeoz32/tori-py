# Nestpy SQLAlchemy Architecture

## 1. Status and Scope

This document defines the `nestpy-sqlalchemy` integration. The distribution
connects Nestpy singleton lifecycle and dependency injection to SQLAlchemy's
asynchronous engine, session factory, and ORM entity APIs.

The integration owns:

- creation and deterministic disposal of module-owned `AsyncEngine` values;
- registration of externally owned engines without taking ownership;
- one singleton `async_sessionmaker` per configured root;
- one singleton `EntityManager` per root;
- short-lived lexical transactions and nested savepoints opened by that manager;
- guarded same-task ambient transaction propagation through an instance-owned
  `ContextVar`;
- SQLAlchemy-native, generic entity operations without model registration;
- synchronous and DI-resolved asynchronous root configuration;
- deterministic keyed tokens for multiple database roots.

The integration does not own:

- request-scoped session providers or cross-task session propagation;
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
        global_: bool = True,
    ) -> DeferredModule: ...

    @classmethod
    def for_root_async(
        cls,
        *,
        use_factory: SqlAlchemyOptionsFactory,
        imports: Iterable[ModuleImport] = (),
        key: str = "default",
        global_: bool = True,
    ) -> DeferredModule: ...

    @classmethod
    def for_engine(
        cls,
        engine: AsyncEngine | Token,
        *,
        session: SqlAlchemySessionOptions = SqlAlchemySessionOptions(),
        imports: Iterable[ModuleImport] = (),
        key: str = "default",
        global_: bool = True,
    ) -> DeferredModule: ...

    @classmethod
    def for_feature(
        cls,
        features: Iterable[type[object]],
        *,
        key: str = "default",
    ) -> DeferredModule: ...
```

`for_root()` owns its engine. `for_engine()` never disposes its external engine.
`for_root_async()` registers its sync-or-async `use_factory` directly as a
singleton Nestpy provider. Factory dependencies use annotations and
`Annotated[..., Inject(token)]`; no separate `inject=[]` API exists.

Roots are global by default so repository feature modules can resolve the keyed
`EntityManager` without a descriptor reference or process-global registry.
`global_=False` remains an explicit opt-out and is incompatible with implicit
`for_feature()` lookup. Feature modules themselves are not global.

## 5. Providers and Tokens

Every root has canonical qualified singleton providers:

```text
nestpy_sqlalchemy:<key>:engine
nestpy_sqlalchemy:<key>:session_factory
nestpy_sqlalchemy:<key>:entity_manager
```

For `key="default"`, `AsyncEngine` and `EntityManager` are additional aliases.
Named roots expose only qualified tokens:

```python
get_engine_token(key="analytics")
get_session_factory_token(key="analytics")
get_entity_manager_token(key="analytics")
```

There is no `AsyncSession` provider or `get_session_token()`. Application
singletons therefore cannot accidentally retain operation state.

## 6. EntityManager

`EntityManager` is one concurrency-safe singleton per root. It stores the
singleton session factory and one instance-owned `ContextVar`; it never stores a
session in an ordinary shared attribute. `transaction()` yields that same
singleton manager:

```python
async with entities.transaction() as transaction:
    assert transaction is entities
    member = await members.get_one(member_id, with_for_update=True)
    await audits.add(AuditRow(member_id=member.id, action="updated"))
    total = await transaction.scalar(select(func.count()).select_from(AuditRow))
```

The outermost context creates a fresh session, begins a transaction, commits on
success, rolls back on failure, and always closes the session even when
finalization fails. Every standalone CRUD, query, or statement operation first
checks the contextual state. A valid transaction owned by the current task is
reused directly without a savepoint. With no current state, the operation opens
its own top-level transaction, commits or rolls back, and closes its session
before returning. Standalone writes therefore commit automatically, and
standalone reads return buffered, detached results.

Calling `transaction()` again on the same manager in the same task opens
`AsyncSession.begin_nested()` and yields the same manager. A caught nested
failure rolls back its savepoint while leaving the outer transaction active.
SQLAlchemy may flush pending state before creating a savepoint even when
`autoflush=False`.

Each top-level task has a distinct contextual state and session. Child tasks
inherit Python context values, so every operation validates that
`asyncio.current_task()` is the owning task. Inherited child-task and escaped
contextual state raise `TransactionContextError` rather than silently opening an
independent operation transaction.
Independent transactions from different roots remain independent and are not a
distributed transaction.

The manager exposes `add()`, `add_all()`, `get()`, `get_one()`, `merge()`,
`delete()`, `flush()`, `refresh()`, and buffered `execute()`, `scalar()`, and
`scalars()`. It does not expose commit, rollback, close, or streaming results;
the manager-owned operation or lexical context owns finalization. Locking reads
with `with_for_update=True` require an explicit active transaction so the lock
outlives the method call. `flush()` is likewise transaction-local because no Unit
of Work survives a completed standalone operation.
Standalone `refresh()` temporarily reattaches the supplied entity, refreshes it,
and expunges the attached graph before commit so unrelated detached changes do
not become writes.

## 7. Repositories

`Repository[EntityT]` is a model-bound façade over its keyed singleton
`EntityManager`. It exposes model-bound CRUD plus `find()`,
`find_one()`, `find_one_or_raise()`, `count()`, and `exists()` using native
SQLAlchemy expressions, loader options, ordering, and bounded offset/limit
values. It does not accept criteria dictionaries or define a separate query
language. Repository methods reuse the manager's active contextual session or
receive a standalone operation transaction automatically.

Default repository DI is explicit:

```python
task_persistence = SqlAlchemyModule.for_feature([TaskRow])


class TaskService:
    def __init__(
        self,
        tasks: Annotated[
            Repository[TaskRow],
            inject_repository(TaskRow),
        ],
    ) -> None:
        self._tasks = tasks
```

`inject_repository(Entity, key=...)` is a normal Nestpy `Inject` marker over a
process-local, mapped-class-identity-backed repository token. `for_feature()`
receives mapped classes explicitly; it performs no module, model, or constructor
scanning.

Applications add persistence policy by declaring a concrete repository:

```python
@repository(TaskRow)
class TaskRepository(Repository[TaskRow]):
    async def find_overdue(self) -> tuple[TaskRow, ...]:
        rows = await self._scalars(
            select(TaskRow).where(TaskRow.due_at < utcnow())
        )
        return tuple(rows)
```

Decorated repositories are stateless singleton providers and use their concrete
class as the DI token. They MUST directly specialize `Repository[Entity]`,
inherit the base constructor, and cannot declare additional constructor
dependencies. Shared intermediate repository base classes are intentionally not
supported. `for_feature([TaskRow, TaskRepository])` may register the default and
custom repositories together. Python's type system preserves the concrete
decorated class but cannot express its dependent entity-type equality; the
decorator validates that equality eagerly at import time.

Several repositories automatically share one transaction when called from the
same owning task. They are never cloned or bound, and no transaction argument is
passed through application layers.

## 8. Application Providers

Stateless services and controllers SHOULD be singleton providers:

```python
@injectable()
class MemberService:
    def __init__(self, entities: EntityManager) -> None:
        self._entities = entities

    async def update(self, member_id: int) -> None:
        async with self._entities.transaction():
            member = await self._members.get_one(member_id)
            member.activate()
```

Explicit transaction contexts SHOULD be used only for the narrowest contiguous
atomic persistence work, locks, or savepoints. A standalone manager or repository
call needs no surrounding context. Awaiting unrelated network or policy work
while holding a database transaction SHOULD be avoided.

## 9. Models and Migrations

The application owns `DeclarativeBase`, mappings, metadata, repository policy,
and migrations. Repository registration is explicit and does not generate
classes, scan models, maintain a process-global model registry, or add a
TypeORM-like criteria language.

Complex queries remain normal SQLAlchemy statements. Alembic remains a separate
deployment tool, and the integration performs no DDL during startup.

## 10. Testing

Contract tests MUST verify:

- the manager is singleton and creates no session during startup;
- each concurrent top-level transaction receives a distinct session;
- success commits and closes exactly once;
- failure rolls back and closes exactly once;
- standalone operations auto-scope transactions and reuse an active transaction;
- the manager yielded by every scope is the singleton itself;
- same-task nesting uses savepoints with bounded rollback;
- child-task and escaped-context operations fail explicitly;
- repositories automatically share one identity map and transaction;
- keyed roots resolve distinct managers;
- owned and external engine disposal semantics;
- real async-driver add/get/query/update/delete and rollback behavior;
- default/custom repository DI, rich query, ambient transaction, and keyed-root behavior;
- public API, import boundaries, type marker, wheel, and sdist artifacts.

## 11. Non-Goals

The distribution does not add HTTP middleware, CQRS, event sourcing, outbox,
retries, model discovery, generated repositories, custom query builders,
automatic migrations, health checks, tenant engine caches, read/write splitting,
two-phase commit, or database-driver-specific APIs.
