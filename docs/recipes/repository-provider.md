# Repository Provider

Bind application code to a repository interface token, keep the implementation
in an infrastructure module, and export only the interface. This preserves
module boundaries and gives tests one supported replacement point.

## Declare the token and implementation

Class and `Protocol` objects are valid provider tokens. The implementation does
not need framework inheritance:

```python
from typing import Protocol


class TaskRepository(Protocol):
    async def add(self, title: str) -> int: ...

    async def get(self, task_id: int) -> str | None: ...


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self._next_id = 1
        self._tasks: dict[int, str] = {}

    async def add(self, title: str) -> int:
        task_id = self._next_id
        self._next_id += 1
        self._tasks[task_id] = title
        return task_id

    async def get(self, task_id: int) -> str | None:
        return self._tasks.get(task_id)
```

Bind the interface token explicitly and export that token:

```python
from tori_py import ClassProvider, injectable, module


@module(
    providers=[ClassProvider(TaskRepository, InMemoryTaskRepository)],
    exports=[TaskRepository],
)
class PersistenceModule:
    pass


@injectable()
class TaskService:
    def __init__(self, tasks: TaskRepository) -> None:
        self._tasks = tasks

    async def create(self, title: str) -> int:
        return await self._tasks.add(title.strip())


@module(
    imports=[PersistenceModule],
    providers=[TaskService],
    exports=[TaskService],
)
class TasksModule:
    pass
```

The constructor annotation selects `TaskRepository`. If the annotation type and
provider token should differ, use `Annotated[TaskRepository, Inject(TOKEN)]`.
Tori Py does not instantiate unregistered annotation types or discover
repository implementations.

## Scope and lifecycle

The declaration above is singleton by default. That is appropriate only for a
stateless repository or a concurrency-safe in-memory implementation.

- A singleton repository may depend only on singleton-safe dependencies.
- Do not store request, transaction, actor, or message state in a singleton.
- If the implementation is a context manager, `ClassProvider` manages it by
  default and injects the entered value. It opens at application startup and
  closes during rollback or shutdown.
- A request-scoped repository is valid, but a singleton service cannot inject
  it. Make the consuming service request-scoped or resolve it inside a fresh
  work scope.
- An alias provider changes visibility, not ownership. It does not create or
  close another repository instance.

For database repositories, prefer the integration's transaction model rather
than inventing request sessions. `tori-py-sqlalchemy` registers default and
custom repositories explicitly:

```python
from typing import Annotated

from tori_py_sqlalchemy import (
    Repository,
    SqlAlchemyModule,
    inject_repository,
    repository,
)


@repository(TaskRow)
class SqlTaskRepository(Repository[TaskRow]):
    pass


task_persistence = SqlAlchemyModule.for_feature([TaskRow, SqlTaskRepository])


class SqlTaskService:
    def __init__(
        self,
        tasks: Annotated[Repository[TaskRow], inject_repository(TaskRow)],
        custom_tasks: SqlTaskRepository,
    ) -> None:
        self._tasks = tasks
        self._custom_tasks = custom_tasks
```

Those repositories are stateless singletons over a singleton `EntityManager`.
Standalone operations create and close their own transactions; operations in an
explicit same-task `EntityManager.transaction()` reuse it. Repositories are not
cloned or bound, and no `AsyncSession` escapes through DI.

## Replace the public token in a test

`TestingModule` applies overrides before graph compilation. The target is the
module that owns and exports the provider, not a module that merely imports it:

```python
from typing import cast

from tori_py import module
from tori_py.testing import TestingModule


class FakeTaskRepository:
    def __init__(self) -> None:
        self.titles: list[str] = []

    async def add(self, title: str) -> int:
        self.titles.append(title)
        return 41

    async def get(self, task_id: int) -> str | None:
        return None


@module(imports=[TasksModule])
class AppModule:
    pass


fake = FakeTaskRepository()
testing = TestingModule.create(AppModule)
testing.override_provider(
    TaskRepository,
    module=PersistenceModule,
).use_value(fake)
application = await testing.compile()
try:
    service = cast(TaskService, await application.resolve(TaskService))
    assert await service.create("Write a test") == 41
    assert fake.titles == ["Write a test"]
finally:
    await application.close()
```

`use_value()` is externally owned: Tori Py does not call resource enter/exit on
the fake. Use an override class or factory when construction by the test graph is
part of the behavior under test. Remember that an override is a replacement
provider declaration; test the intended scope and ownership rather than assuming
the original declaration's scope is retained.

Private providers cannot be overridden from outside their owner module. Export
the interface token deliberately; do not export the concrete implementation
only to make a test pass.

## Test the right boundary

- Unit-test repository query or storage policy without Tori Py when no DI or
  lifecycle behavior is involved.
- Compile a `TestingModule` to prove token visibility, constructor injection,
  scope, and managed-resource behavior.
- Use `TestingApplication.http_client()` to test the observable controller path.
  The testing application already owns lifespan; the HTTPX client must not start
  a second one.
- Run real database tests for transaction isolation, locks, migrations, and
  driver behavior. An in-memory repository replacement proves application
  orchestration, not database correctness.

## Production boundary

The framework does not add persistence, migrations, retries, an outbox, or
idempotency to this repository. If one operation must update several repositories
atomically, use the persistence adapter's explicit transaction boundary. If a
database update must cause durable message delivery, use an application-owned
transactional outbox rather than publishing directly from the repository.
