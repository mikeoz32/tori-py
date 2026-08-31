# SQLAlchemy

`tori-py-sqlalchemy` connects ToriPy dependency injection and application
lifecycle to SQLAlchemy's asynchronous APIs. It provides:

- one singleton `AsyncEngine`, async session factory, and `EntityManager` per
  configured database root;
- deterministic tokens for applications that use more than one database;
- explicit default and custom repository registration;
- automatic transactions for standalone persistence operations;
- explicit transaction composition and same-task nested savepoints.

The integration does not place an `AsyncSession` in dependency injection. A
singleton service or repository can safely retain an `EntityManager`; the
manager selects a short-lived session from task-local transaction state for
each operation.

## Install

Install the integration and the async driver selected by the application. The
integration depends on SQLAlchemy's asyncio support, but deliberately does not
choose or install a database driver.

For SQLite:

```text
uv add tori-py-sqlalchemy aiosqlite
```

Use a URL such as `sqlite+aiosqlite:///application.db`.

For PostgreSQL with Psycopg:

```text
uv add tori-py-sqlalchemy psycopg
```

Use a URL such as
`postgresql+psycopg://user:password@localhost/application`.
The pure Python Psycopg package requires the PostgreSQL `libpq` client library
on the host or in the container. At the time of writing, the `psycopg[binary]`
extra does not publish an artifact for every Python 3.14 platform supported by
ToriPy, so do not assume it is portable across development and deployment.

For PostgreSQL with asyncpg:

```text
uv add tori-py-sqlalchemy asyncpg
```

Use a URL such as
`postgresql+asyncpg://user:password@localhost/application`.

The URL's dialect and driver name must match the installed driver. Driver
configuration, supported database features, pooling behavior, and deployment
remain application concerns.

## Minimal Setup

Define mappings and metadata in the application, configure a database root,
and register each repository explicitly:

```python
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from tori_py import module
from tori_py_sqlalchemy import (
    SqlAlchemyModule,
    SqlAlchemyOptions,
)


class Base(DeclarativeBase):
    pass


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120), unique=True)


database = SqlAlchemyModule.for_root(
    SqlAlchemyOptions(
        url="sqlite+aiosqlite:///application.db",
        engine_options={"pool_pre_ping": True},
    )
)
task_persistence = SqlAlchemyModule.for_feature([TaskRow])


@module(imports=[database, task_persistence])
class AppModule:
    pass
```

`for_root()` creates and owns the engine. ToriPy disposes it during application
shutdown and also unwinds it if startup fails. No table is created by this
configuration. The application owns `Base.metadata` and should normally evolve
the schema with Alembic.

## Guides

- [Configuration](configuration.md) covers root variants, ownership, session
  options, and keyed databases.
- [Repositories](repositories.md) covers default and custom repositories,
  dependency injection, and native SQLAlchemy queries.
- [Transactions](transactions.md) covers automatic operation transactions,
  detached entities, explicit atomic work, savepoints, and concurrency guards.
- [Testing and migrations](testing-and-migrations.md) covers `TestingModule`
  replacements, test databases, metadata ownership, and Alembic.

The complete runnable example is in
`examples/tori_py/reference_apps/sqlalchemy_task_api/`.

## Boundaries

The package is intentionally narrow. It does not provide synchronous sessions,
request-scoped sessions, model scanning, generated repository classes, a custom
criteria language, streaming results, startup migrations, health checks,
tenant or replica routing, distributed transactions, retries, an outbox, CQRS,
or event sourcing.
