# nestpy-sqlalchemy

`nestpy-sqlalchemy` connects Nestpy application/request scopes to SQLAlchemy's
async engine and session lifecycle. It does not add implicit transactions,
repositories, model registration, migrations, CQRS, or event sourcing.

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

Application services own native SQLAlchemy transaction boundaries:

```python
from sqlalchemy.ext.asyncio import AsyncSession


class CreateMemberService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, row: MemberRow) -> None:
        async with self._session.begin():
            self._session.add(row)
```

`for_root()` creates and owns an engine. `for_engine()` registers an externally
owned engine and never disposes it. The default root exports `AsyncEngine` and
`AsyncSession` for type-based injection. Named roots use explicit tokens:

```python
from typing import Annotated

from nestpy import Inject
from nestpy_sqlalchemy import get_session_token


class AnalyticsRepository:
    def __init__(
        self,
        session: Annotated[
            AsyncSession,
            Inject(get_session_token(key="analytics")),
        ],
    ) -> None:
        self._session = session
```

The integration does not install a database driver. Applications select and
install one, such as psycopg, and own their SQLAlchemy models, repositories, and
Alembic migrations.
