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
`SessionManager`, and `EntityManager` providers. The default root also exports
their class aliases. No `AsyncSession` is stored in DI.

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

No feature registration is needed when DI is unnecessary:

```python
tasks = entities.repository(TaskRow)
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

## One-Shot Operations

```python
from nestpy import injectable
from nestpy_sqlalchemy import EntityManager


@injectable()
class MemberService:
    def __init__(self, entities: EntityManager) -> None:
        self._entities = entities

    async def create(self, name: str) -> MemberRow:
        return await self._entities.add(MemberRow(name=name))

    async def get(self, member_id: int) -> MemberRow | None:
        return await self._entities.get(MemberRow, member_id)
```

One-shot write methods open a session and transaction, flush, commit or roll
back, and close automatically. Returned ORM entities are detached; load required
relationships explicitly. The default `expire_on_commit=False` keeps loaded
attributes available. Opting into `expire_on_commit=True` means detached return
values may instead contain expired attributes.

## Atomic Composition

```python
async with entities.transaction() as transaction:
    members = member_repository.bind(transaction)
    audits = transaction.repository(AuditRow)
    member = await members.get_one(member_id, with_for_update=True)
    member.rename(name)
    await audits.add(AuditRow(member_id=member.id, action="renamed"))
```

The bound `EntityTransaction` exposes entity operations but not `commit()`,
`rollback()`, or `close()`. The context owns transaction finalization.
Keep locked reads and dependent writes in this same context because a one-shot
call releases locks before returning. Repository binding rejects inactive or
wrong-root transactions and does not mutate singleton repositories.

## Low-Level Sessions

```python
from nestpy_sqlalchemy import SessionManager


async with sessions.session() as session:
    async with session.begin():
        await session.execute(statement)

async with sessions.transaction() as session:
    await session.execute(statement)
```

`SessionManager` and `EntityManager` are concurrency-safe singletons because
they retain only the singleton `async_sessionmaker`; each call creates a fresh
session. A session or bound `EntityTransaction` is single-task state and must
not be shared between concurrent tasks.

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
