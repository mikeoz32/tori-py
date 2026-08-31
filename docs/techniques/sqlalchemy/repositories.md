# SQLAlchemy Repositories

Repositories are explicit, stateless singleton providers bound to one mapped
class and one keyed `EntityManager`. They add a small model-specific facade while
retaining SQLAlchemy expressions, loader options, result exceptions, and query
semantics.

## Application Models

The application owns its declarative base, mappings, metadata, relationships,
and naming conventions:

```python
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(120), unique=True)
    completed: Mapped[bool] = mapped_column(default=False)
```

The integration does not scan this metadata or create tables.

## Default Repository

Register mapped classes explicitly with the root's key:

```python
from tori_py_sqlalchemy import SqlAlchemyModule


task_persistence = SqlAlchemyModule.for_feature([TaskRow])
```

Inject the resulting default repository with `inject_repository()`:

```python
from typing import Annotated

from tori_py_sqlalchemy import Repository, inject_repository


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

For a named root, use the same key both when registering and injecting:

```python
analytics_persistence = SqlAlchemyModule.for_feature(
    [TaskRow],
    key="analytics",
)


class AnalyticsTaskService:
    def __init__(
        self,
        tasks: Annotated[
            Repository[TaskRow],
            inject_repository(TaskRow, key="analytics"),
        ],
    ) -> None:
        self._tasks = tasks
```

`get_repository_token(TaskRow, key=...)` returns the same canonical token when a
test or infrastructure module needs to refer to the provider directly. The token
uses mapped-class identity within the current process; persist neither it nor its
rendered string.

## CRUD

The default repository exposes model-bound operations:

```python
created = await tasks.add(TaskRow(title="Document transactions"))
first, second = await tasks.add_all(
    (
        TaskRow(title="Add tests"),
        TaskRow(title="Run migrations"),
    )
)

found = await tasks.get(created.id)
required = await tasks.get_one(created.id)

created.title = "Document SQLAlchemy transactions"
merged = await tasks.merge(created)
await tasks.delete(merged)
```

`get()` returns `None` for a missing primary key. `get_one()` propagates
SQLAlchemy's `NoResultFound`. `add()`, `add_all()`, `merge()`, and `delete()`
flush before returning and commit when they are standalone calls. The returned
entities detach when that operation's session closes.

`merge()` is the explicit way to persist modified detached state. It returns the
managed copy used by SQLAlchemy, not necessarily the object passed to it.

## Query Patterns

Pass native SQLAlchemy expressions rather than dictionaries or repository-specific
criteria objects:

```python
rows = await tasks.find(
    TaskRow.completed.is_(False),
    TaskRow.title.startswith("Doc"),
    order_by=(TaskRow.id.desc(),),
    offset=0,
    limit=50,
)
```

`find()` returns a tuple and applies SQLAlchemy result uniqueness. `offset` must
be a non-negative integer; `limit` must be a positive integer. Production list
operations should normally set a deterministic order and bounded limit.

Use loader options for relationships that must remain available after the
standalone query closes:

```python
from sqlalchemy.orm import selectinload


project = await projects.find_one_or_raise(
    ProjectRow.id == project_id,
    options=(selectinload(ProjectRow.tasks),),
)
```

Single-row helpers preserve exact-result behavior:

```python
optional = await tasks.find_one(TaskRow.title == title)
required = await tasks.find_one_or_raise(TaskRow.title == title)
```

`find_one()` returns `None` for no row. `find_one_or_raise()` propagates
`NoResultFound`. Both propagate `MultipleResultsFound` if more than one row
matches; they are not implicit "first row" operations.

Counting and existence checks also accept native expressions:

```python
remaining = await tasks.count(TaskRow.completed.is_(False))
duplicate = await tasks.exists(TaskRow.title == title)
```

Primary-key loads and single-row queries accept `with_for_update=True`, but a
locking read requires an explicit transaction so the lock survives beyond the
method call:

```python
async with entities.transaction():
    task = await tasks.get_one(task_id, with_for_update=True)
    task.completed = True
```

## Custom Repository

Declare application-specific query policy by directly specializing
`Repository[Entity]` and decorating the concrete class:

```python
from sqlalchemy import select
from tori_py_sqlalchemy import Repository, repository


@repository(TaskRow)
class TaskRepository(Repository[TaskRow]):
    async def find_incomplete(self, *, limit: int) -> tuple[TaskRow, ...]:
        rows = await self._scalars(
            select(TaskRow)
            .where(TaskRow.completed.is_(False))
            .order_by(TaskRow.id)
            .limit(limit)
        )
        return tuple(rows)
```

Register and inject the concrete class directly:

```python
task_persistence = SqlAlchemyModule.for_feature([TaskRepository])


class TaskService:
    def __init__(self, tasks: TaskRepository) -> None:
        self._tasks = tasks
```

Register both declarations when consumers need both repository forms:

```python
task_persistence = SqlAlchemyModule.for_feature([TaskRow, TaskRepository])
```

The default repository and custom repository are distinct singleton instances,
but both use the same keyed manager and therefore share an explicit transaction
in its owning task.

A custom repository must:

- be decorated directly with `@repository(Entity)`;
- directly specialize `Repository[Entity]` for the same mapped class;
- inherit the base `Repository` constructor unchanged;
- remain stateless and declare no additional constructor dependencies.

Use inherited `_execute()`, `_scalar()`, and `_scalars()` in custom query methods.
They return buffered SQLAlchemy results and participate in the same automatic or
explicit transaction rules as the built-in methods. Shared intermediate custom
repository base classes and generated repositories are intentionally unsupported.

For cross-aggregate, reporting, or bulk operations that do not fit one mapped
class, inject `EntityManager` and execute a normal SQLAlchemy statement instead
of forcing the query into a repository.
