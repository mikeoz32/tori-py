# SQLAlchemy Configuration

Configure one SQLAlchemy root for each independently managed database. A root
exports a singleton async engine, async session factory, and `EntityManager`.
The default root also exports the `AsyncEngine` and `EntityManager` classes as
convenient dependency-injection aliases.

All integration imports in these examples come from the package facade:

```python
from tori_py_sqlalchemy import (
    EntityManager,
    SqlAlchemyModule,
    SqlAlchemyOptions,
    SqlAlchemySessionOptions,
    get_engine_token,
    get_entity_manager_token,
    get_session_factory_token,
)
```

## Owned Root

Use `for_root()` when configuration is already available while declaring the
module:

```python
database = SqlAlchemyModule.for_root(
    SqlAlchemyOptions(
        url="postgresql+psycopg://app:secret@localhost/application",
        engine_options={
            "pool_pre_ping": True,
            "pool_size": 10,
        },
    )
)
```

This root owns the engine created from `SqlAlchemyOptions`. It creates the engine
during application startup and disposes it during shutdown or startup rollback.
The options object is immutable, defensively copies `engine_options`, and omits
the URL and engine options from its representation to reduce accidental secret
exposure. It is not a secret manager; keep credentials in application settings
or another appropriate secret source.

`engine_options` is passed to SQLAlchemy's `create_async_engine()`. Do not put a
second `url` entry in it.

## DI-Resolved Configuration

Use `for_root_async()` when database settings are supplied by another module.
The factory may be synchronous or asynchronous and uses normal annotation-based
ToriPy injection:

```python
from tori_py.settings import SettingsModule, SettingsOptions


settings_module = SettingsModule.for_root(
    SettingsOptions(model=AppSettings, env_prefix="APP_"),
    global_=True,
)


def create_database_options(settings: AppSettings) -> SqlAlchemyOptions:
    return SqlAlchemyOptions(
        url=settings.database_url,
        engine_options={"pool_pre_ping": True},
    )


database = SqlAlchemyModule.for_root_async(
    imports=[settings_module],
    use_factory=create_database_options,
)
```

The factory is a singleton provider and is resolved once during startup. It must
return `SqlAlchemyOptions`. This variant also creates, owns, and disposes its
engine.

## External Engine

Use `for_engine()` when another component owns an existing `AsyncEngine`:

```python
from sqlalchemy.ext.asyncio import create_async_engine


engine = create_async_engine("sqlite+aiosqlite:///application.db")
database = SqlAlchemyModule.for_engine(engine)
```

The root builds its session factory and manager around the supplied engine, but
never disposes the engine. The code that called `create_async_engine()` must call
`await engine.dispose()` after the ToriPy application has stopped.

An engine may instead be supplied through an exported ToriPy provider token:

```python
database = SqlAlchemyModule.for_engine(
    "infrastructure.primary_engine",
    imports=[engine_module],
)
```

The token must resolve to an `AsyncEngine`. Supplying a token also leaves
lifecycle ownership with its original provider.

## Session Options

Each root creates one async session factory. Its defaults are deliberately
explicit:

```python
session_options = SqlAlchemySessionOptions(
    expire_on_commit=False,
    autoflush=False,
    autobegin=False,
)

database = SqlAlchemyModule.for_root(
    SqlAlchemyOptions(
        url="sqlite+aiosqlite:///application.db",
        session=session_options,
    )
)
```

- `expire_on_commit=False` keeps already-loaded attributes readable after the
  operation closes and detaches the entity.
- `autoflush=False` avoids query-triggered flushes. Repository write methods
  still flush explicitly, and SQLAlchemy may flush when committing or opening a
  nested savepoint.
- `autobegin=False` ensures transaction creation remains under the manager's
  control.

Custom session options can also be passed to `for_engine(session=...)`. Enabling
`expire_on_commit` can leave returned detached attributes expired. Enabling
`autobegin` weakens the integration's explicit transaction assumptions and
should only be done for a deliberate SQLAlchemy policy.

## Keyed Roots

The key separates every canonical provider. Keep the default key for the primary
database and use named roots for additional databases:

```python
primary_database = SqlAlchemyModule.for_root(
    SqlAlchemyOptions(url=settings.primary_database_url)
)
analytics_database = SqlAlchemyModule.for_root(
    SqlAlchemyOptions(url=settings.analytics_database_url),
    key="analytics",
)
```

Inject the default manager by class:

```python
class PrimaryService:
    def __init__(self, entities: EntityManager) -> None:
        self._entities = entities
```

Named roots expose only keyed tokens:

```python
from typing import Annotated

from tori_py import Inject


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

The other canonical tokens are available for infrastructure integrations:

```python
analytics_engine_token = get_engine_token(key="analytics")
analytics_session_factory_token = get_session_factory_token(key="analytics")
```

There is no `AsyncSession` provider. Application services should normally use an
`EntityManager` or repository rather than resolving the session factory.

Keys must be non-empty strings and cannot be `"static"`. Reuse the same key for
the root and its repository features:

```python
analytics_tasks = SqlAlchemyModule.for_feature(
    [AnalyticsTaskRow],
    key="analytics",
)
```

Each root has independent transactions. Opening transactions against two roots
does not create a distributed transaction or coordinate their commits.

## Global Visibility

Roots are global by default because `for_feature()` resolves the matching keyed
manager without retaining a root descriptor or using a process-global model
registry:

```python
database = SqlAlchemyModule.for_root(options, global_=True)
tasks = SqlAlchemyModule.for_feature([TaskRow])
```

Set `global_=False` only when module-local visibility is required. An opted-out
root cannot back `for_feature()`'s implicit manager lookup. In that case, import
the local root along the normal module visibility path and inject its keyed
`EntityManager` directly instead of registering an implicit feature module.
