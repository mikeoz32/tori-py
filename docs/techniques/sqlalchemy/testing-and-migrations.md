# SQLAlchemy Testing And Migrations

Tests and migrations preserve the same ownership boundary as production code:
the application owns mappings, metadata, schema policy, test database setup, and
migration history. `tori-py-sqlalchemy` owns only the engine it creates through
`for_root()` or `for_root_async()`.

## Test Dependencies

Install the test runner and a lightweight async driver in the application:

```text
uv add --dev pytest pytest-asyncio aiosqlite
```

For ASGI tests using ToriPy's HTTP client, install the testing extra:

```text
uv add --dev 'tori-py-framework[testing]'
```

Run tests through uv:

```text
uv run pytest
```

SQLite is useful for fast repository and lifecycle tests, but it does not prove
PostgreSQL locking, isolation, constraint, type, SQL, or production pooling
behavior. Keep database-specific integration tests against the production
database engine where those semantics matter.

## Replace The Database Root

`TestingModule` applies replacements before the module graph starts. A useful
pattern is to create an external test engine, initialize the application-owned
metadata, and replace the production root with `for_engine()`:

```python
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingModule
from tori_py_sqlalchemy import SqlAlchemyModule

from application.app import AppModule
from application.database import Base, database


@pytest.mark.asyncio
async def test_persistence(tmp_path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        test_database = SqlAlchemyModule.for_engine(engine)
        builder = TestingModule.create(AppModule)
        builder.replace_module(database, test_database)
        application = await builder.compile(adapter=StarletteAdapter())
        try:
            # Resolve services or use application.http_client() here.
            pass
        finally:
            await application.close()
    finally:
        await engine.dispose()
```

The original descriptor passed to `replace_module()` identifies the dynamic
module and key. Match the production root's key when replacing a named root:

```python
test_analytics = SqlAlchemyModule.for_engine(
    engine,
    key="analytics",
)
builder.replace_module(analytics_database, test_analytics)
```

`for_engine()` does not own the engine, so the test disposes it after closing the
testing application. Closing the application first ensures every session and
provider has stopped using the engine.

## Override Canonical Providers

For a narrower test, override the canonical keyed engine token in its dynamic
root module:

```python
from tori_py_sqlalchemy import get_engine_token


builder = TestingModule.create(AppModule)
builder.override_provider(
    get_engine_token(),
    module=database,
).use_value(engine)
application = await builder.compile()
```

The existing session-factory and manager providers are then built around the
replacement. The replacement is a plain value, so the test still owns and must
dispose the engine. Prefer the canonical keyed token rather than overriding only
the default root's `AsyncEngine` alias; consumers may inject either the alias or
the keyed resource.

`override_global(get_engine_token(key=...))` can target a globally exported root
without naming its module. A module-targeted override is clearer when a graph
contains multiple roots.

Only exported providers can be overridden. `TestingModule.compile()` starts the
application and seals the builder; call `application.close()` in `finally` to
run normal production shutdown.

## Override Repositories

Default repositories use their canonical repository token. Target the exact
feature descriptor returned by `for_feature()`:

```python
from tori_py_sqlalchemy import get_repository_token

from application.tasks import TaskRow, task_persistence


fake_tasks = FakeTaskRepository()
builder = TestingModule.create(AppModule)
builder.override_provider(
    get_repository_token(TaskRow),
    module=task_persistence,
).use_value(fake_tasks)
```

A custom repository's concrete class is its token:

```python
builder.override_provider(
    TaskRepository,
    module=task_persistence,
).use_value(fake_tasks)
```

Use the same `key` in `get_repository_token()` for a named feature. Provider
replacement is useful for application-service tests; repository contract tests
should use a real `Repository` and async driver so SQL expressions, rollback,
detachment, and constraint behavior remain exercised.

## Metadata In Tests

Direct `Base.metadata.create_all()` is appropriate for isolated test databases
and runnable demonstrations when the application explicitly owns that setup:

```python
async with engine.begin() as connection:
    await connection.run_sync(Base.metadata.create_all)
```

It is not performed by `SqlAlchemyModule`. For tests that reuse a database, make
cleanup explicit through database recreation, transactions managed by the test
harness, or application-owned `drop_all()` setup. Do not expect a transaction
opened outside `EntityManager` to become the manager's contextual transaction;
the integration intentionally has no external-session binding API.

## Alembic Migrations

Place Alembic where the process that runs migrations can install it. A dedicated
migration dependency group keeps it out of the application runtime while making
it available to deployment jobs:

```text
uv add --group migrations alembic
uv run --group migrations alembic init -t async migrations
```

If Alembic is used only to author revisions locally, `uv add --dev alembic` is
also valid, but an environment synchronized without the development group cannot
run `alembic upgrade`. A deployment image must install either the normal project
dependency or the dedicated migration group.

Import the application's declarative base in Alembic's `env.py` and set its
metadata as the autogenerate target:

```python
from application.database.models import Base

target_metadata = Base.metadata
```

Configure Alembic's database URL through the application's deployment settings
or Alembic configuration. Keep credentials out of committed files. Then create,
review, and apply revisions through uv:

```text
uv run --group migrations alembic revision --autogenerate -m "create task tables"
uv run --group migrations alembic upgrade head
```

Autogenerate produces a candidate migration, not a verified schema change.
Review generated types, names, constraints, indexes, server defaults, and data
migrations before applying it.

Production application startup should not call `Base.metadata.create_all()` or
run Alembic implicitly. Apply migrations as a separate deployment step before
starting replicas. This avoids concurrent startup DDL, hidden privilege
requirements, and application instances racing to mutate the schema.

The integration provides no Alembic wrapper, migration CLI, model discovery,
startup DDL, health check, or schema compatibility gate. Those remain explicit
application and deployment responsibilities.