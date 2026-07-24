# nestpy-sqlalchemy

`nestpy-sqlalchemy` connects Nestpy singleton lifecycle and DI to SQLAlchemy's
async engine, session factory, and entity operations. It does not add model
scanning, generated repositories, a custom query language, migrations, CQRS, or
event sourcing.

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

The default root exports singleton `AsyncEngine`, `SessionManager`, and
`EntityManager` providers. No `AsyncSession` is stored in DI.

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
    member = await transaction.get_one(MemberRow, member_id)
    member.rename(name)
    transaction.add(AuditRow(member_id=member.id, action="renamed"))
    await transaction.flush()
```

The bound `EntityTransaction` exposes entity operations but not `commit()`,
`rollback()`, or `close()`. The context owns transaction finalization.
Keep locked reads and dependent writes in this same context because a one-shot
call releases locks before returning.

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

Applications install their selected async driver and own SQLAlchemy models,
metadata, query policy, and Alembic migrations.
