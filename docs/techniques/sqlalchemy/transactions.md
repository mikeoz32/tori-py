# SQLAlchemy Transactions

`EntityManager` is a singleton facade over short-lived async sessions. Each
manager owns an instance-specific `ContextVar` that identifies the transaction
for the current asyncio task. Repositories associated with that manager use the
same context automatically.

## Standalone Operations

Ordinary standalone CRUD, query, and statement-execution operations open a
fresh session and top-level transaction:

```python
created = await tasks.add(TaskRow(title="Write guide"))
loaded = await tasks.get(created.id)
count = await tasks.count()
```

Each call follows this lifecycle independently:

1. Open a session.
2. Begin a transaction.
3. Execute and buffer the operation's result.
4. Commit on success or roll back on failure.
5. Close the session before returning or re-raising.

This applies to reads as well as writes. A failed standalone write does not
leave transaction state behind, so a later operation can open a new session.
Cancellation and transaction-finalization failures also run session cleanup.

`EntityManager.flush()` is deliberately not a standalone operation, and any
manager or repository call with `with_for_update=True` requires an active
explicit transaction. Neither case creates a short-lived automatic transaction;
the [Flush and locks](#flush-and-locks) section covers those boundaries.

## Detached Entities

An ORM entity returned by a standalone operation is detached because its session
has already closed. The same is true after an explicit transaction context exits.
With the default `expire_on_commit=False`, attributes that were loaded remain
available:

```python
task = await tasks.get_one(task_id)
return TaskResponse(id=task.id, title=task.title)
```

Lazy-loading after return cannot use the closed session. Load every relationship
needed outside the operation with SQLAlchemy loader options:

```python
from sqlalchemy.orm import selectinload


project = await projects.get_one(
    project_id,
    options=(selectinload(ProjectRow.tasks),),
)
```

Setting `expire_on_commit=True` can also expire scalar attributes before the
entity detaches, making post-operation access unsafe. Returning transport DTOs
instead of ORM entities makes the boundary explicit.

Changing a detached entity does not start a Unit of Work. Use `merge()` for a
single detached update:

```python
task = await tasks.get_one(task_id)
task.title = new_title
updated = await tasks.merge(task)
```

For read-modify-write behavior that must use one identity map and one atomic
transaction, use an explicit context instead.

Standalone `refresh()` temporarily attaches the supplied entity, refreshes the
requested state, and expunges the attached graph before committing. This avoids
accidentally committing unrelated changes already present on the detached graph.

## Explicit Atomic Work

Inject the manager associated with the repositories and keep the transaction
around the narrowest contiguous database work:

```python
from tori_py_sqlalchemy import EntityManager


class TaskService:
    def __init__(
        self,
        entities: EntityManager,
        tasks: TaskRepository,
        audits: AuditRepository,
    ) -> None:
        self._entities = entities
        self._tasks = tasks
        self._audits = audits

    async def complete(self, task_id: int) -> None:
        async with self._entities.transaction() as transaction:
            assert transaction is self._entities
            task = await self._tasks.get_one(task_id, with_for_update=True)
            task.completed = True
            await self._audits.add(
                AuditRow(task_id=task.id, action="completed")
            )
```

The outer context creates one session and transaction. Every manager and
repository operation using that same keyed manager in the owning task reuses the
active session directly. An ordinary operation inside the context does not open
another transaction or savepoint. On normal exit SQLAlchemy flushes pending
changes and commits; an exception rolls back the whole transaction.

`transaction()` yields the same singleton `EntityManager`, not a session or a
separate transaction object. It intentionally exposes no `commit()`,
`rollback()`, or `close()` controls. Lexical context exit owns finalization.

Avoid awaiting unrelated network calls while holding a database transaction.
Validate inputs and perform remote work before opening the context when possible.

## Flush And Locks

`flush()` is transaction-local:

```python
async with entities.transaction():
    task = await tasks.add(TaskRow(title="Assigned id"))
    await entities.flush()
    task_id = task.id
```

Repository write methods already flush. Calling `EntityManager.flush()` outside
an active explicit transaction raises `TransactionContextError` because no Unit
of Work survives a standalone call.

Likewise, `with_for_update=True` requires an explicit transaction. An automatic
one-method read would release the row lock before the caller could safely act on
the result.

## Nested Savepoints

Calling `transaction()` again on the same manager from the same task opens a
native SQLAlchemy savepoint:

```python
async with entities.transaction():
    await tasks.add(TaskRow(title="kept before savepoint"))

    try:
        async with entities.transaction():
            await tasks.add(TaskRow(title="rolled back to savepoint"))
            raise DuplicateTask
    except DuplicateTask:
        pass

    await tasks.add(TaskRow(title="kept after savepoint"))
```

If the nested exception is caught outside the nested context, only work within
that savepoint is rolled back and the outer transaction remains active. A later
failure in the outer context still rolls back both outer work and every
successfully released savepoint.

SQLAlchemy may flush pending state before `AsyncSession.begin_nested()`, even
when `autoflush=False`. Do not assume that entering a savepoint is free of
database writes or constraint checks.

## Task Ownership

A transaction belongs to the asyncio task that opened it. Python copies context
variables into child tasks, but an `AsyncSession` cannot safely be shared that
way. The manager therefore checks task identity on every operation:

```python
async with entities.transaction():
    child = asyncio.create_task(tasks.count())
    await child  # raises TransactionContextError
```

Do not use `asyncio.create_task()`, `TaskGroup`, or `asyncio.gather()` to run
repository work concurrently inside one explicit transaction. Execute that work
sequentially in the owning task. An inherited context used after the parent
transaction exits is also rejected as no longer active rather than silently
opening an unrelated transaction.

Independent top-level tasks that do not inherit an active transaction receive
distinct sessions and can run standalone operations concurrently. Parallel
transactions on different keyed roots are also independent; the integration
does not provide distributed commit or rollback.