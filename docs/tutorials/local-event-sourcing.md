# Event-Source Tasks in One Process

This tutorial continues [Part 2: Add CQRS](cqrs-application.md) in the same
`task-api` project. Instead of a repository that overwrites the current task,
the application stores every change as an event and rebuilds state from those
events. Everything runs in one process on the in-memory event store, with no
broker.

[Part 4: Add Event Sourcing](event-sourced-application.md) uses event sourcing
across several processes connected by RabbitMQ. This tutorial stays in one
process so that the parts Part 4 does not show each get a step: a change to the
stored event format, version conflicts, and commits whose result is unknown.

The continuity rules are:

- the existing routes are unchanged: same paths, payloads, and Problem Details;
- one route is new: `PATCH /tasks/{task_id}` renames a task;
- `POST /tasks`, `GET /tasks/{task_id}`, and `PATCH` return an `ETag` header
  with the task's version;
- a read right after a write still sees the write, unlike in Part 4.

Part 2 also published an in-process `TaskCreated` notification from the command
handler to an audit log and a metrics counter. With an event store, publishing
inside the handler happens before the commit, so the notification could describe
a task that was never stored;
[Persistence and EventBus Publication](../techniques/event-sourcing/tori-py.md#persistence-and-eventbus-publication)
explains the `after_commit` alternative and its limits. This tutorial removes
the observers to keep the focus on the store.

## What You Will Build

```text
POST /tasks, PATCH /tasks/{id}
  └─▶ CommandBus ─▶ CreateTaskHandler, RenameTaskHandler   (one Unit of Work each)
                      └─▶ TaskAggregate ─▶ TaskRepository.save()
                                             └─▶ commit ─▶ InMemoryEventStore
                                                                 │
GET /tasks, GET /tasks/{id}                                      │ read_all()
  └─▶ QueryBus ─▶ GetTaskHandler, ListTasksHandler               │
                    └─▶ TaskProjection.catch_up() ◀──────────────┘
```

| Feature | Technique |
| --- | --- |
| State rebuilt from history | `AggregateRoot` with `raise_event()` and `_apply()` |
| Stored names that outlive Python classes | `EventSchema` aliases in a frozen `EventSchemaRegistry` |
| Changing a stored format | An upcaster from schema version 1 to version 2 |
| One transaction per command | `@use_event_sourcing` |
| Reads | A projection with a checkpoint over `EventStore.read_all()` |
| No lost updates between clients | `ETag` and `If-Match` |
| Two writers of one version | `OptimisticConcurrencyError` |
| A commit nobody can confirm | `IndeterminateCommitError` and `after_indeterminate()` |

## Continue In The Part 2 Project

Open the `task-api` directory you completed in Part 2 and add the event-sourcing
packages from the same checkout:

```text
uv add --editable "../tori-py/packages/tori-py-cqrs-event-sourcing-core"
uv add --editable "../tori-py/packages/tori-py-cqrs-event-sourcing"
```

`tori-py-cqrs-event-sourcing-core` contains aggregates, schemas, the event store
protocol, the in-memory store, and the Unit of Work; it does not depend on
ToriPy. `tori-py-cqrs-event-sourcing` runs ToriPy command handlers inside a Unit
of Work.

When this tutorial is complete, the project has this shape:

```text
task-api/
  task_app/
    __init__.py         package marker
    models.py           replace
    domain.py           new
    schemas.py          new
    state.py            replace
    projection.py       new
    reconciliation.py   new
    messages.py         replace
    handlers.py         replace
    http.py             replace
    app.py              replace
    testing.py          new
    test_domain.py      new
    test_app.py         replace
```

Delete `task_app/services.py` and `task_app/observers.py`. The aggregate and the
command handlers take over the service's work.

## Step 1: Model The Aggregate

Replace `task_app/models.py`:

```python
--8<-- "examples/tori_py/tutorials/local_event_sourced_task_api/task_app/models.py"
```

`Task`, `CreateTaskBody`, and the two Part 2 errors are unchanged.
`RenameTaskBody` is the `PATCH` body, and the two new errors become `400` and
`412` in Step 6.

Create `task_app/domain.py`:

```python
--8<-- "examples/tori_py/tutorials/local_event_sourced_task_api/task_app/domain.py"
```

`TaskCreated` and `TaskRenamed` are domain events: facts in the past tense. They
are `tori_py_cqrs_core.Event` subclasses, but nothing publishes them; they are
what the store keeps.

`TaskAggregate` makes decisions in `create()` and `rename()`. Each method checks
the title rule and calls `raise_event()`, which applies the event to the
aggregate and records it as pending. `rename()` to the current title records
nothing.

`_apply()` changes state and nothing else. The repository also calls it to
replay stored events, and those events were valid when they were written, so
`_apply()` does not check the title rule again.

`version` is the last committed stream version. A new aggregate has version `0`;
pending events do not change it until a commit is confirmed.

## Step 2: Give Stored Events Stable Names

Create `task_app/schemas.py`:

```python
--8<-- "examples/tori_py/tutorials/local_event_sourced_task_api/task_app/schemas.py"
```

Each `EventSchema` binds a stored alias, such as `tasks.task-created`, to an event
class, a schema version, an encoder, and a decoder. The alias is what the store
keeps, so a Python class can be renamed or moved without breaking stored
history. The registry is frozen before use; an unfrozen registry or a late
registration is an error.

The `msgspec` structs use `forbid_unknown_fields=True`, so stored JSON with a
missing, extra, or mistyped field fails with `EventCodecError`, or
`EventUpcastError` inside an upcaster, instead of producing a half-built event.

Suppose the first release of this service wrote task-created as
`{"id": 7, "name": "Legacy"}`. Version 2 writes `{"task_id": 7, "title": "..."}`.
Stored events are never rewritten. Instead, `upcast_task_created_v1` turns
version 1 bytes into version 2 bytes while reading, before the version 2 decoder
runs. A schema at version `N` needs an upcaster for each version from `1` to
`N - 1`, and new events are always written at the current version. Step 9 stores
a version 1 event and reads it back.

## Step 3: Declare The Repository

Replace `task_app/state.py`:

```python
--8<-- "examples/tori_py/tutorials/local_event_sourced_task_api/task_app/state.py"
```

`@aggregate_repository(TaskAggregate, category="task", id_encoder=str)` stores
each task in its own stream, `StreamId("task", "1")` for task `1`. The category
and the encoded ID are part of the stored data, like the aliases.

`EVENT_STORE_KEY` names the event-sourcing root that Step 7 registers. Handlers
and the projection use it to select that root's store, schemas, and transaction.

`TaskIdSequence` hands out IDs from memory. That is enough for one process with
an in-memory store; both start over on restart.

## Step 4: Handle Commands In A Unit Of Work

Replace `task_app/messages.py`:

```python
--8<-- "examples/tori_py/tutorials/local_event_sourced_task_api/task_app/messages.py"
```

The commands and `GetTask` return a `VersionedTask`, a task together with its
stream version, so the controller can set the `ETag`. `RenameTask` carries the
version the client expects, or `None` when the client sent no `If-Match`.

Create `task_app/reconciliation.py`:

```python
--8<-- "examples/tori_py/tutorials/local_event_sourced_task_api/task_app/reconciliation.py"
```

Replace `task_app/handlers.py`:

```python
--8<-- "examples/tori_py/tutorials/local_event_sourced_task_api/task_app/handlers.py"
```

`@use_event_sourcing(key=EVENT_STORE_KEY)` goes above `@command_handler(...)`.
For each command it opens one Unit of Work, gives the request-scoped repository
that transaction, and commits after `handle()` returns. When `handle()` raises,
it rolls back. The handler only loads, decides, and calls `save()`, which stages
the pending events; it never calls `commit()`. Handlers that inject a repository
must use `Scope.REQUEST`.

`RenameTaskHandler` uses `load()`, which returns `None` for a task without a
stream, and raises the Part 2 `TaskNotFound`. If the client sent a version and
the task has moved on, it raises `TaskVersionMismatch` before deciding anything.

The handler returns the version the task will have after the commit: the loaded
version plus the pending events. The caller receives it only after the commit is
confirmed, and a confirmed commit appends exactly those events.

`after_indeterminate()` registers a callback for one outcome: the store could not
say whether the commit happened. The callback records the task in
`ReconciliationLog`. It must not undo anything, because the event may be stored.
A real application would persist the entry and have a job compare it with the
store. Step 6 shows what the client sees.

## Step 5: Read From A Projection

Create `task_app/projection.py`:

```python
--8<-- "examples/tori_py/tutorials/local_event_sourced_task_api/task_app/projection.py"
```

`TaskProjection` reads committed events in global order with `read_all()`,
starting after its checkpoint, the global position of the last event it applied.
It decodes them through the same registry, so upcasters apply here too, and keeps
each task with its stream version.

The query handlers in Step 4 call `catch_up()` before reading. The command bus
returns only after the commit, and the projection reads the same store, so a
`GET` after a `POST` or `PATCH` sees the change. The lock lets one caller catch
up at a time.

Queries never use the repository. Repositories exist only inside a decorated
command; resolving one anywhere else raises `CommandTransactionUnavailableError`.

The checkpoint lives in memory with the read model, so both start from the
beginning on restart. With a durable store, a projection keeps its checkpoint in
the same transaction as its read model.

## Step 6: Expose Versions Over HTTP

Replace `task_app/http.py`:

```python
--8<-- "examples/tori_py/tutorials/local_event_sourced_task_api/task_app/http.py"
```

`task_response()` returns the task as JSON with `ETag: "N"`, where `N` is the
stream version. `PATCH` reads `If-Match`:

- no `If-Match` renames whatever the current version is;
- `If-Match: "N"` renames only if the task is still at version `N`, and returns
  `412` otherwise, so a client cannot overwrite a change it has not seen;
- a weak or malformed value returns `400`.

`TaskErrorFilter` maps each error to Problem Details:

| Error | Status | Meaning |
| --- | --- | --- |
| `TaskTitleInvalid` | `400` | The title breaks the rule from Part 2 |
| `InvalidIfMatch` | `400` | `If-Match` is not an ETag from this API |
| `TaskNotFound` | `404` | No stream exists for the ID |
| `TaskVersionMismatch` | `412` | The client read an older version |
| `OptimisticConcurrencyError` | `409` | Another writer committed between this command's load and commit |
| `IndeterminateCommitError` | `503` | It is unknown whether the change was stored |

`409` cannot happen yet. The in-memory command transport runs one command at a
time, so two commands in this process never overlap. It appears as soon as a
second process writes to the same durable store. Step 9 produces it with a test
store.

`503` does not mean the write failed. The detail tells the client to read the
task before retrying, because a blind retry of `POST /tasks` could create a
second task.

## Step 7: Compose The Application

Replace `task_app/app.py`:

```python
--8<-- "examples/tori_py/tutorials/local_event_sourced_task_api/task_app/app.py"
```

`PersistenceModule` provides `InMemoryEventStore` as an ordinary provider.
`CqrsEventSourcingModule.for_root()` receives that provider token, not a store
object, together with the frozen schemas and the key. The root is global and
exports only tokens qualified by the key, among them the store, schemas, and
command synchronization that the handlers and the projection inject. Import it
exactly once, in the application module.

`CqrsEventSourcingModule.for_feature([TaskRepository], root_key=EVENT_STORE_KEY)`
registers the repository for that root. `TasksModule` imports the feature module
and registers the handlers, the projection, the ID sequence, and the
reconciliation log.

`PIPELINE` names the global pipe and filter so that tests can apply the same
pipeline.

## Step 8: Run It

Start the server from the `task-api` root:

```text
uv run tori-py run task_app.app:create_application
```

Create a task, rename it with the version you received, then try the same
version again:

=== "PowerShell"

    ```powershell
    '{"title":"Plan"}' | curl.exe --silent --show-error --include -X POST "http://127.0.0.1:8000/tasks" -H "content-type: application/json" --data-binary '@-'
    '{"title":"Plan the release"}' | curl.exe --silent --show-error --include -X PATCH "http://127.0.0.1:8000/tasks/1" -H "content-type: application/json" -H 'If-Match: "1"' --data-binary '@-'
    '{"title":"Lost update"}' | curl.exe --silent --show-error --include -X PATCH "http://127.0.0.1:8000/tasks/1" -H "content-type: application/json" -H 'If-Match: "1"' --data-binary '@-'
    ```

=== "Bash"

    ```bash
    curl --silent --show-error --include -X POST "http://127.0.0.1:8000/tasks" \
      -H "content-type: application/json" --data '{"title":"Plan"}'
    curl --silent --show-error --include -X PATCH "http://127.0.0.1:8000/tasks/1" \
      -H "content-type: application/json" -H 'If-Match: "1"' \
      --data '{"title":"Plan the release"}'
    curl --silent --show-error --include -X PATCH "http://127.0.0.1:8000/tasks/1" \
      -H "content-type: application/json" -H 'If-Match: "1"' \
      --data '{"title":"Lost update"}'
    ```

The create returns `201` with `etag: "1"`, the first rename returns `200` with
`etag: "2"`, and the second rename returns `412 Precondition Failed`, because the
task is no longer at version 1. `GET /tasks/1` returns `Plan the release` with
`etag: "2"`.

Everything is lost when the process stops: the event store, the projection, and
the ID sequence.

## Step 9: Test It

Create `task_app/testing.py`:

```python
--8<-- "examples/tori_py/tutorials/local_event_sourced_task_api/task_app/testing.py"
```

`FaultyStore` forwards to an `InMemoryEventStore` and implements the same
`EventStore` protocol. When a test sets `armed`, its next commit fails in one of
two ways:

- `CompetingWriterStore` first commits the same events through a second
  transaction, as another process writing the same task would. The real commit
  then fails with the store's own `OptimisticConcurrencyError`.
- `LostAcknowledgementStore` commits and then raises `IndeterminateCommitError`,
  as a database adapter does when the connection drops before the commit is
  acknowledged.

Create `task_app/test_domain.py`:

```python
--8<-- "examples/tori_py/tutorials/local_event_sourced_task_api/task_app/test_domain.py"
```

These tests use the core package without the ToriPy application. They check
that:

1. the aggregate records the right events and keeps the title rule;
2. a Unit of Work commits a task, advances its version, and a new Unit of Work
   replays it;
3. a version 1 event written directly to the store is upcast when the repository
   and the projection read it;
4. of two Units of Work that loaded the same version, the second to commit gets
   `OptimisticConcurrencyError` with both versions, and its aggregate is faulted
   and must be loaded again.

Replace `task_app/test_app.py`:

```python
--8<-- "examples/tori_py/tutorials/local_event_sourced_task_api/task_app/test_app.py"
```

The HTTP tests check that:

1. the Part 2 HTTP contract still holds;
2. `ETag` and `If-Match` behave as Step 6 describes;
3. with `CompetingWriterStore`, a rename returns `409`, and a retry with the
   current `ETag` succeeds;
4. with `LostAcknowledgementStore`, a create returns `503`, the reconciliation
   log holds the task, and the task is stored anyway.

`_compile_with()` replaces the store through
`override_provider(get_event_store_token(key=EVENT_STORE_KEY), module=...)`.
That keyed token is what the transactions and the projection resolve, so both
use the test store.

Run them:

```text
uv run pytest task_app -q
```

Expected result: `8 passed`.

## Guarantees And Limits

- **Not durable.** `InMemoryEventStore` keeps events in one process. Tori Py
  does not include a database event store; an adapter must implement the
  [store contract](../techniques/event-sourcing/stores-repositories-uow.md),
  including reporting an unknown commit outcome as `IndeterminateCommitError`.
- **One process.** Task IDs come from memory, so two processes would hand out the
  same IDs.
- **Nothing is published.** Persisting an event does not deliver it anywhere.
  Reliable publication needs an outbox written in the same database transaction
  as the events.
- **`503` is not a failure.** Reconcile before retrying. Stable command IDs and
  idempotent handling are application work.
- **Catch-up runs on every read.** That is fine at this size. A larger system runs
  projections separately, with durable checkpoints.
- **Upcasters run on every read.** They never rewrite stored events, so old
  versions stay readable for as long as their upcasters exist.

## Next Steps

- [Aggregates and Schemas](../techniques/event-sourcing/aggregates-and-schemas.md):
  recording, replay, faulting, metadata, codecs, and upcasters.
- [Stores, Repositories, and Unit of Work](../techniques/event-sourcing/stores-repositories-uow.md):
  transactions, optimistic concurrency, and commit outcomes.
- [Event Sourcing with ToriPy](../techniques/event-sourcing/tori-py.md): roots,
  features, synchronization callbacks, and finalization errors.
- [Part 4: Add Event Sourcing](event-sourced-application.md): an event-sourced
  service across several processes with persistent streams.
