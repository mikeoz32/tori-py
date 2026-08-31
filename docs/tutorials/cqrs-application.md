# Task API, Part 2: Add CQRS

This tutorial continues [Part 1](task-api.md) in the same `task-api`
project. Do not initialize another project, replace the existing package, or
change the HTTP API. You will route the existing application service through
command and query buses, then publish a task-created event to asynchronous audit
and metrics observers.

The central continuity rule is:

- `task_app/models.py`, `task_app/state.py`, and `task_app/services.py` remain
  byte-for-byte unchanged from Part 1;
- `POST /tasks` still returns `201` with only the created task;
- reads still use the same repository and are immediately consistent after a
  successful create;
- validation and Problem Details responses remain the same;
- CQRS types and observer state do not appear in the HTTP contract.

CQRS changes how the application dispatches work. It does not require changing
the business rules or public API.

## Continue In The Part 1 Project

Open the `task-api` directory that you completed in Part 1. Its existing
framework, msgspec, CLI, HTTPX, pytest, and pytest-asyncio dependencies remain in
place. Add only the two editable CQRS distributions:

```text
uv add --editable "../tori-py/packages/tori-py-cqrs-core"
uv add --editable "../tori-py/packages/tori-py-cqrs"
```

The explicit core dependency lets `uv` satisfy the integration package's local
version constraint from the same checkout. Do not re-add the Part 1 dependencies.

When this part is complete, the package has this shape:

```text
task-api/
  .python-version
  pyproject.toml
  uv.lock
  task_app/
    __init__.py       unchanged package marker
    models.py         unchanged
    state.py          unchanged
    services.py       unchanged
    messages.py       new
    observers.py      new
    handlers.py       new
    http.py           replace
    app.py            replace
    test_app.py       replace
```

## Preserve The HTTP Contract

The same three routes retain the same inputs and outputs:

| Request | Success | Application failure |
| --- | --- | --- |
| `POST /tasks` with `{"title":"..."}` | `201` with `{"id":1,"title":"..."}` | `400` for a normalized title outside 1-120 characters |
| `GET /tasks` | `200` with tasks in ID order | None |
| `GET /tasks/{task_id}` | `200` with one task | `404` when the ID is absent |

The global msgspec pipe still rejects malformed JSON, a missing `title`, unknown
body fields, and non-integer path values with `400` Problem Details. Titles are
still trimmed by `TaskService`, IDs still start at 1, and no architecture
metadata is added to a response.

The only request-path change is internal:

```text
Part 1
HTTP controller -> TaskService -> TaskRepository

Part 2
HTTP controller -> CommandBus -> CreateTaskHandler -> TaskService -> TaskRepository
                -> QueryBus   -> query handler      -> TaskService -> TaskRepository

CreateTaskHandler -> EventBus -> AuditTaskCreated -> TaskAuditLog
                             +-> CountTaskCreated -> TaskMetrics
```

The query handlers deliberately call the unchanged `TaskService`, which reads
the same singleton `TaskRepository` written by the command handler. Therefore,
after `await commands.execute(...)` succeeds, a subsequent query in this process
can observe the task immediately. The audit and metrics branches are separate,
asynchronous reactions and are not part of the read path.

!!! note "A deliberately small CQRS design"

    More advanced CQRS systems may introduce a separately persisted read model
    with an explicit consistency policy. That is not necessary to teach message
    routing, handler discovery, or event fan-out, and it would break Part 1's
    immediate-read behavior. This tutorial keeps one repository on purpose.

## Keep The Part 1 Application Code

Do not edit the next three files. They are repeated here so the page remains
self-contained and so the unchanged boundary is explicit.

### `task_app/models.py`

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/models.py"
```

### `task_app/state.py`

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/state.py"
```

### `task_app/services.py`

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/services.py"
```

`TaskService` remains the owner of title normalization and validation. The
handlers added below delegate to it instead of copying business behavior into
CQRS classes.

## Add The Messages

Create `task_app/messages.py`:

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/messages.py"
```

The generic parameters describe command and query result types. Runtime routing
uses the exact concrete message class: `CreateTask`, `GetTask`, or `ListTasks`.
Each command or query has exactly one handler. An event can have zero or more
handlers, which allows `TaskCreated` to fan out.

`CreateTask` carries the already validated `CreateTaskBody` from the HTTP
adapter. `TaskCreated` carries the immutable task returned by the unchanged
service.

## Add The Asynchronous Observers

Create `task_app/observers.py`:

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/observers.py"
```

These observers are singleton, process-local educational state. They do not
participate in task reads and do not change the HTTP response. Their bounded
condition waits let tests prove that each asynchronous handler reached its
effect without using arbitrary sleeps.

## Add The Handlers

Create `task_app/handlers.py`:

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/handlers.py"
```

The command handler calls `TaskService.create()` first, publishes the resulting
`TaskCreated`, and returns the same `Task`. The query handlers are equally thin:
they delegate `get()` and `all()` to the unchanged service. CQRS routing has not
moved domain behavior out of the service.

`EventBus.publish()` waits for transport acceptance, not for either event
handler to finish. The event worker schedules `AuditTaskCreated` and
`CountTaskCreated` independently. Their start and completion order is not
guaranteed, and one handler's failure does not roll back the repository write or
an effect already completed by the other handler.

The three decorators attach both handler and injectable-provider metadata. They
do not globally register the classes and do not scan the Python package. Every
handler must still be listed in a compiled module's `providers`.

## Replace The HTTP Adapter

Replace all of `task_app/http.py` with:

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/http.py"
```

The controller diff is intentionally narrow. Its constructor changes from one
`TaskService` dependency to `CommandBus` and `QueryBus`; each route wraps its
validated input in a message and awaits the relevant bus. Route paths, body and
path bindings, result annotations, create status, and the error filter preserve
the Part 1 contract.

The controller does not inject handlers, the repository, or observer state. HTTP
is now an adapter around the two request/reply buses, while application failures
still cross the adapter and reach the same filter.

## Replace The Composition Root

Replace all of `task_app/app.py` with:

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/app.py"
```

`InfrastructureModule`, `TaskRepository`, `TaskService`, the validation pipe,
the error filter, and the application factory preserve their Part 1 roles. The
composition adds three things:

- `CqrsModule.for_root(global_=True)` creates and globally exports one
  application CQRS graph containing `CommandBus`, `QueryBus`, and `EventBus`;
- `TasksModule` owns the observer providers and all five handlers;
- `AppModule` imports the CQRS root so its lifecycle is part of the application.

The global CQRS root makes its exported buses visible to the controller and
handlers without re-exporting them through each feature module. The state and
handlers remain private to `TasksModule`; private providers are still eligible
for CQRS discovery from the complete compiled graph.

## Understand Discovery, Scopes, And Lifecycle

All providers in this application use the default managed singleton scope.
`TaskRepository`, `TaskService`, `TaskAuditLog`, and `TaskMetrics` each have one
application instance. The handler decorators also default to managed singleton,
so each handler instance is reused.

Bus invocation scopes still matter even with singleton handlers:

- every command and query dispatch opens its own CQRS work scope;
- each event handler invocation opens a separate work scope, so the two
  `TaskCreated` reactions can overlap;
- a CQRS work scope is independent of the surrounding HTTP request scope;
- ambient HTTP context and request-scoped resources are not propagated into a
  handler invocation.

If a handler is later declared with `scope=Scope.REQUEST`, "request" means one
instance per CQRS invocation, not one instance per HTTP request. Safe application
data needed by a handler must be carried explicitly in its message.

During graph assembly, CQRS discovery reads decorated providers from the
compiled module graph. It validates metadata, dependency visibility, and scope
paths. Duplicate command or query handlers for the same exact message type fail
composition. A message with no registered request/reply handler fails when it is
dispatched. Events retain registration scheduling order, but not start or
completion order.

Application lifecycle owns all three default in-memory transports:

```text
startup
  -> build the registry and acquire transports
  -> start event delivery
  -> start query delivery
  -> start command delivery
  -> admit application requests

graceful shutdown
  -> stop and drain commands
  -> stop and drain queries
  -> stop and drain events and tracked event tasks
  -> release managed resources
```

`create_application()` returns an unstarted application. The CLI and exported
`asgi()` wrapper let ASGI lifespan call startup and shutdown. Direct tests must
start and shut down an application explicitly unless they use
`TestingModule.compile()`, which starts lifecycle during compilation.

## Replace The Tests

Replace all of `task_app/test_app.py` with:

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/test_app.py"
```

Run the complete Part 2 test file from the `task-api` project root:

```text
uv run pytest task_app/test_app.py -q
```

The stable result is:

```text
...                                                                      [100%]
3 passed
```

Elapsed time varies. The three tests cover distinct boundaries:

1. Direct command and query execution proves normalization, application errors,
   and immediate repository-backed reads without HTTP.
2. Direct event observation proves that one `TaskCreated` reaches both audit and
   metrics handlers.
3. In-process ASGI requests preserve the complete Part 1 HTTP contract,
   including malformed JSON, body validation, path conversion, ordering, and
   Problem Details.

The HTTP test uses the production controller, pipeline, handlers, and lifecycle,
but HTTPX's ASGI transport does not exercise sockets, TLS, proxies, workers, or
operating-system signals.

## Use `EventBus.drain()` Correctly

`EventBus.drain()` waits for event-handler and error-observer tasks that are
already tracked when draining begins. It is not a transport-queue barrier.
Immediately after `publish()` returns, an event can still be queued while no
handler task has been created, so calling `drain()` alone can return before the
expected effects occur.

That is why the event test follows this order:

```text
execute CreateTask
  -> wait up to one second for the audit effect
  -> wait up to one second for the metrics effect
  -> drain tracked event tasks within the remaining test step
  -> assert observer state
```

The application-level conditions prove that the relevant handlers processed the
event; `drain()` then waits for tracked work. If its timeout expires, drain
requests cancellation and returns rather than raising `TimeoutError`. Code that
resists cancellation may still be running. Graceful `EventBus.shutdown()` is a
stronger boundary for the default in-memory transport because it first closes
and drains transport admission before draining tracked handler tasks.

## Run The Application

Start the same project from its root:

```text
uv run tori-py run task_app.app:create_application
```

The process ID in Uvicorn's other log lines varies. The readiness line identifies
the default address:

```text
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

In another PowerShell session, send the same HTTP requests used in Part 1. The
`--write-out` suffix makes each status explicit:

```powershell
'{"title":"  Learn CQRS with Tori Py  "}' | curl.exe --silent --request POST "http://127.0.0.1:8000/tasks" --header "content-type: application/json" --data-binary '@-' --write-out "`nHTTP %{http_code}`n"
```

Exact application output:

```text
{"id":1,"title":"Learn CQRS with Tori Py"}
HTTP 201
```

Read the collection and the new task:

```powershell
curl.exe --silent "http://127.0.0.1:8000/tasks" --write-out "`nHTTP %{http_code}`n"
curl.exe --silent "http://127.0.0.1:8000/tasks/1" --write-out "`nHTTP %{http_code}`n"
```

Exact application output, in command order:

```text
[{"id":1,"title":"Learn CQRS with Tori Py"}]
HTTP 200
{"id":1,"title":"Learn CQRS with Tori Py"}
HTTP 200
```

An invalid normalized title retains the same `400` Problem Details response:

```powershell
'{"title":"   "}' | curl.exe --silent --request POST "http://127.0.0.1:8000/tasks" --header "content-type: application/json" --data-binary '@-' --write-out "`nHTTP %{http_code}`n"
```

```text
{"type":"about:blank","title":"Bad Request","status":400,"detail":"After trimming, the task title must contain 1-120 characters.","instance":"/tasks"}
HTTP 400
```

An absent ID retains the same `404` Problem Details response:

```powershell
curl.exe --silent "http://127.0.0.1:8000/tasks/999" --write-out "`nHTTP %{http_code}`n"
```

```text
{"type":"about:blank","title":"Not Found","status":404,"detail":"Task was not found.","instance":"/tasks/999"}
HTTP 404
```

Stop the server normally so ASGI lifespan can stop accepting work, drain the
CQRS buses, and release managed resources. The exported wrapper remains
available for direct Uvicorn hosting:

```text
uv run uvicorn task_app.app:application --lifespan on
```

## Guarantees And Limits

This Part 2 application demonstrates and tests these guarantees:

- the external HTTP contract is unchanged from Part 1;
- exact command and query types route to one discovered handler each;
- handlers preserve business behavior by delegating to `TaskService`;
- a completed create command is immediately visible to subsequent queries in
  the same application process;
- one accepted `TaskCreated` is independently offered to both registered event
  handlers;
- only providers in the explicitly compiled module graph are discovered;
- application lifecycle starts, quiesces, drains, and closes the CQRS graph;
- tests can exercise buses directly or cross the complete HTTP adapter.

It does not provide production durability or delivery guarantees:

- tasks, IDs, audit entries, metrics, transports, and queued work exist only in
  one process and are lost on restart;
- separate workers have separate repositories and therefore do not share the
  immediate-read behavior;
- the default in-memory event transport is process-local and at-most-once;
- the repository write and event publication are not atomic; publication can
  fail after the task was stored;
- event publication success does not mean either observer finished;
- event-handler failures do not roll back a task and are not retried, requeued,
  dead-lettered, or replayed by this application;
- there is no outbox, event store, idempotency key, exactly-once execution,
  cross-process messaging, or distributed transaction;
- a timeout or cancellation does not prove that accepted work had no effect;
- the educational application still has no authentication, authorization,
  durable audit facility, persistence migration, or multi-worker coordination.

These are application boundaries, not gaps hidden by CQRS. Durable persistence,
event publication, retries, and reconciliation require explicit designs owned by
the application.

## Continue To Part 3: Distributed Decomposition

Part 2 still has one application root, one repository, and process-local event
delivery. [Part 3: Distributed Decomposition](distributed-application.md)
preserves the same HTTP contract while separating an HTTP gateway, a task
service that owns task state and local CQRS, and an audit service that consumes a
versioned integration event. It introduces typed RPC, service ownership,
at-least-once delivery, deduplication, and the failure boundary between storing a
task and publishing an event.
