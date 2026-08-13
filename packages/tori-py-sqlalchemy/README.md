# tori-py-sqlalchemy

`tori-py-sqlalchemy` connects ToriPy singleton lifecycle and DI to SQLAlchemy's
async engine, session factory, entity operations, and explicit repositories. It
does not add model scanning, generated repository classes, a custom query
language, migrations, CQRS, or event sourcing.

```python
from tori_py_sqlalchemy import SqlAlchemyModule, SqlAlchemyOptions


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

## Automatic Operations

```python
from tori_py import injectable


@injectable()
class MemberService:
    def __init__(self, members: MemberRepository) -> None:
        self._members = members

    async def create(self, name: str) -> MemberRow:
        return await self._members.add(MemberRow(name=name))

    async def get(self, member_id: int) -> MemberRow | None:
        return await self._members.get(member_id)
```

Each standalone manager or repository operation opens a fresh transaction,
commits or rolls back, and always closes its session. If the current task already
owns an explicit transaction, the operation reuses it without creating a
savepoint. `transaction()` yields the same singleton manager, so direct operations
remain available without another transaction type:

```python
async with entities.transaction() as transaction:
    assert transaction is entities
    count = await transaction.scalar(select(func.count()).select_from(MemberRow))
```

ORM entities become detached after the automatic operation or lexical context
closes. Load required relationships before return. The default
`expire_on_commit=False` keeps loaded attributes available; opting into `True`
may leave detached attributes expired.
`flush()` remains transaction-local because no Unit of Work survives a completed
standalone operation.
Standalone `refresh()` temporarily reattaches and then expunges the supplied
entity graph so unrelated detached changes are not committed.

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
child task while the parent transaction is active. Escaped inherited context is
also rejected rather than silently opening a new session. Locking reads require
an explicit transaction so their lock survives the method call.

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
