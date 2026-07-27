# nestpy-sqlalchemy

`nestpy-sqlalchemy` connects Nestpy singleton lifecycle and DI to SQLAlchemy's
async engine, session factory, entity operations, and explicit repositories. It
does not add model scanning, generated repository classes, a custom query
language, migrations, CQRS, or event sourcing.

```python
from nestpy_sqlalchemy import SqlAlchemyModule, SqlAlchemyOptions


def create_sqlalchemy_options(settings: AppSettings) -> SqlAlchemyOptions:
    return SqlAlchemyOptions(
        url=settings.database.url,
        engine_options={"pool_pre_ping": True},
    )


database = SqlAlchemyModule.for_root_async(
    imports=[settings_module],
    use_factory=create_sqlalchemy_options,
)
```

Roots are global by default and export keyed singleton engine, session-factory,
and `EntityManager` providers. The default root also exports `AsyncEngine` and
`EntityManager` class aliases. No `AsyncSession` is stored in DI.

## Default Repositories

Register mapped classes explicitly:

```python
task_persistence = SqlAlchemyModule.for_feature([TaskRow])
```

Then inject a model-bound default repository:

```python
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

The repository provides `add()`, `add_all()`, `get()`, `get_one()`, `merge()`,
`delete()`, `find()`, `find_one()`, `find_one_or_raise()`, `count()`, and
`exists()`. Query criteria, ordering, and loader options are native SQLAlchemy
expressions:

```python
rows = await tasks.find(
    TaskRow.completed.is_(False),
    order_by=(TaskRow.created_at.desc(),),
    limit=50,
)
```

## Custom Repositories

```python
@repository(TaskRow)
class TaskRepository(Repository[TaskRow]):
    async def find_overdue(self) -> tuple[TaskRow, ...]:
        rows = await self._scalars(
            select(TaskRow).where(TaskRow.due_at < utcnow())
        )
        return tuple(rows)


task_persistence = SqlAlchemyModule.for_feature([TaskRow, TaskRepository])
```

The concrete class is its DI token. Custom repositories are stateless, directly
specialize `Repository[Entity]`, inherit the base constructor, and have no
additional constructor dependencies.

## Lexical Transactions

```python
from nestpy import injectable
from nestpy_sqlalchemy import EntityManager


@injectable()
class MemberService:
    def __init__(self, entities: EntityManager, members: MemberRepository) -> None:
        self._entities = entities
        self._members = members

    async def create(self, name: str) -> MemberRow:
        async with self._entities.transaction():
            return await self._members.add(MemberRow(name=name))

    async def get(self, member_id: int) -> MemberRow | None:
        async with self._entities.transaction():
            return await self._members.get(member_id)
```

Every manager and repository operation requires an active transaction. The
outermost context opens a fresh session, commits or rolls back, and always
closes. `transaction()` yields the same singleton manager, so direct operations
remain available without another transaction type:

```python
async with entities.transaction() as transaction:
    assert transaction is entities
    count = await transaction.scalar(select(func.count()).select_from(MemberRow))
```

ORM entities become detached after the lexical context closes. Load required
relationships before exit. The default `expire_on_commit=False` keeps loaded
attributes available; opting into `True` may leave detached attributes expired.

## Atomic Composition

```python
async with entities.transaction() as transaction:
    member = await member_repository.get_one(member_id, with_for_update=True)
    member.rename(name)
    await audit_repository.add(AuditRow(member_id=member.id, action="renamed"))
```

Repositories tied to the same keyed manager automatically share the active
session in the owning task. They are never cloned or bound, and transaction
arguments are not passed through application layers.

## Savepoints

```python
async with entities.transaction():
    await members.add(first)
    try:
        async with entities.transaction():
            await members.add(second)
            raise DuplicateMember
    except DuplicateMember:
        pass
```

Same-task nested contexts use `AsyncSession.begin_nested()` and yield the same
manager. SQLAlchemy may flush pending state before opening the savepoint.

`EntityManager` stores current state only in an instance-owned `ContextVar`.
Parallel top-level tasks receive distinct sessions. Child tasks inherit Python
context values, so an owner-task guard rejects manager or repository use from a
child task. Calls outside a transaction and use through an escaped context raise
`TransactionContextError`.

Named roots use explicit tokens:

```python
class AnalyticsService:
    def __init__(
        self,
        entities: Annotated[
            EntityManager,
            Inject(get_entity_manager_token(key="analytics")),
        ],
    ) -> None:
        self._entities = entities
```

Named default repositories use the same key:

```python
tasks: Annotated[
    Repository[TaskRow],
    inject_repository(TaskRow, key="analytics"),
]
```

`global_=False` opts a root out of global lookup. Such a root cannot back
implicit `for_feature()` providers; import and use its keyed `EntityManager`
directly instead.

Applications install their selected async driver and own SQLAlchemy models,
metadata, query policy, and Alembic migrations.
