# Build a CQRS Task API

This tutorial builds a complete ToriPy CQRS application from an empty directory.
You will define commands, queries, events, handlers, an asynchronous read
projection, an HTTP controller, module composition, application bootstrap, and
tests. No existing example application is required.

Every Python file shown here is complete and copyable. The documentation includes
the files from an executable copy under `examples/tori_py/tutorials/cqrs_task_api`
and CI runs its tests, so the tutorial and the public API cannot drift silently.

## What You Will Build

The application exposes three endpoints:

| Request | CQRS message | Result |
| --- | --- | --- |
| `POST /tasks` | `CreateTask` command | `202` with the created task |
| `GET /tasks` | `ListTasks` query | Tasks currently in the read projection |
| `GET /tasks/{task_id}` | `GetTask` query | One projected task or `404` |

The command side and query side use separate in-memory models:

```text
POST /tasks
  -> CreateTask
  -> CreateTaskHandler
  -> TaskRepository                     write model
  -> TaskCreated
       -> ProjectTaskCreated
       -> TaskProjection                read model
       -> AuditTaskCreated
       -> TaskAuditLog                  second event reaction

GET /tasks
  -> ListTasks
  -> ListTasksHandler
  -> TaskProjection
```

This separation demonstrates CQRS mechanics without pretending that in-memory
state is production persistence. The write, event publication, projection, and
audit update are not one transaction.

## Prerequisites

You need Python `>=3.14,<3.15` and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/).
The tutorial assumes that you already understand basic Python packages,
`async`/`await`, and the ToriPy
[First Application](../getting-started/first-application.md).

The initial `0.1.0` package train is not published on PyPI yet. Clone ToriPy and
create the application as a sibling directory so `uv` can use explicit editable
sources:

```text
git clone https://github.com/mikeoz32/tori-py.git
uv init --python 3.14 --bare cqrs-task-api
cd cqrs-task-api
uv python pin 3.14
```

`uv init --bare` creates only `pyproject.toml`; `uv python pin` adds
`.python-version`. Replace the generated project metadata with this exact
supported Python range:

```toml
[project]
name = "cqrs-task-api"
version = "0.1.0"
requires-python = ">=3.14,<3.15"
dependencies = []
```

Now add the three local distributions and test dependencies:

```text
uv add --editable "../tori-py/packages/tori-py[cli,testing]"
uv add --editable "../tori-py/packages/tori-py-cqrs-core"
uv add --editable "../tori-py/packages/tori-py-cqrs"
uv add --dev pytest pytest-asyncio
```

Adding CQRS core explicitly lets `uv` satisfy the integration package's internal
version constraint from the same checkout instead of querying an unpublished
registry package. The framework extras supply Uvicorn, the `tori-py run`
command, and HTTPX. After the release train is published, this section will use
normal registry requirements instead of editable source paths.

## Create the Project Structure

Create this package and these files:

```text
cqrs-task-api/
  .python-version
  pyproject.toml
  uv.lock
  task_app/
    __init__.py
    models.py
    state.py
    handlers.py
    http.py
    app.py
    test_app.py
```

Add the package marker:

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/__init__.py"
```

The application is split by responsibility rather than by framework artifact:

| File | Responsibility |
| --- | --- |
| `models.py` | HTTP DTOs, CQRS messages, response values, application errors |
| `state.py` | Write repository, query projection, audit sink |
| `handlers.py` | Command, query, and event behavior |
| `http.py` | HTTP-to-CQRS adapter and error mapping |
| `app.py` | Modules, providers, pipeline, and ASGI bootstrap |
| `test_app.py` | Direct-bus and HTTP acceptance tests |

## Step 1: Define Values and Messages

Create `task_app/models.py`:

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/models.py"
```

`Task` and `CreateTaskBody` are msgspec models used at the HTTP boundary.
The CQRS messages are ordinary frozen dataclasses:

- `CreateTask(Command[Task])` declares that command execution returns `Task`.
- `GetTask(Query[Task])` declares one task result.
- `ListTasks(Query[list[Task]])` declares a collection result.
- `TaskCreated(Event)` represents a fact with no request/reply result.

The generic result type is for typing. Runtime routing uses the exact concrete
message class. Commands and queries require exactly one matching handler; events
may have zero or more handlers.

The HTTP body and command are deliberately separate. `CreateTaskBody` describes
untrusted transport input. `CreateTask` is the application message and includes
the actor copied from the HTTP header. A command handler therefore does not need
an HTTP request object.

## Step 2: Add Write and Read State

Create `task_app/state.py`:

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/state.py"
```

`TaskRepository` is the write model. It owns IDs and stores accepted tasks, but
it intentionally has no list or get methods.

`TaskProjection` is the read model. Only the `TaskCreated` event handler updates
it. Query handlers will use `get()` and `all()` instead of reading the write
repository. The projection can therefore lag behind a successful command.

`TaskAuditLog` demonstrates event fan-out: the same event updates a projection
and records an independent reaction. It is not security-grade auditing because
it is neither durable nor atomic with the command.

The two `wait_for_count()` methods are application-level completion signals for
tests. They do not change CQRS delivery semantics and should not become HTTP
polling APIs.

## Step 3: Implement the Handlers

Create `task_app/handlers.py`:

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/handlers.py"
```

The decorators serve two purposes:

1. They declare CQRS handler metadata for one message type.
2. They make the class a ToriPy provider with the selected scope.

The class still has to appear in a module's `providers` list. Decorators do not
register modules, mutate a global registry, or scan packages.

### Command Handler

`CreateTaskHandler` is request-scoped. In CQRS, `Scope.REQUEST` means one fresh
ToriPy work scope for one handler invocation. It does not reuse an ambient HTTP
request scope. Direct bus execution receives the same CQRS scope behavior.

The handler:

1. Normalizes and validates the title.
2. Writes the task through `TaskRepository`.
3. Publishes `TaskCreated` through `EventBus`.
4. Returns the task to the command caller.

Publication waits for transport acceptance, not event-handler completion.
The in-memory event worker can start before or after the command returns.

### Event Handlers

`ProjectTaskCreated` and `AuditTaskCreated` receive the same event independently.
Each event handler runs in its own work scope. The request-scoped projection
handler is constructed once for that delivery. The transient audit handler is
constructed when resolved in its delivery scope.

An event-handler failure is reported asynchronously. It does not roll back the
repository write or another event handler that already completed.

### Query Handlers

Each query has one handler and reads only `TaskProjection`. The query bus does
not know whether that projection is in memory, in SQL, or remote; it only routes
the message and returns the handler result.

## Step 4: Adapt HTTP to CQRS

Create `task_app/http.py`:

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/http.py"
```

The controller is deliberately thin:

- It binds and validates HTTP values.
- It translates those values into commands and queries.
- It returns application results to the HTTP adapter.

The controller does not inject `TaskRepository`, `TaskProjection`, or handler
classes. `CommandBus` and `QueryBus` are the application boundary.

`POST /tasks` returns `202` because the command result does not imply that the
asynchronous projection or audit handler completed. Returning `201` could also
be valid for an API whose contract says only that the write model accepted the
resource, but that distinction must be explicit.

`TaskErrorFilter` translates application failures into HTTP Problem Details.
It re-raises unknown exceptions so ToriPy can apply the next filter or its
sanitized fallback. CQRS core remains independent of HTTP status codes.

!!! note "Why `from __future__ import annotations`?"

    Under Python 3.14's deferred annotation evaluation, the class namespace can
    resolve `list` to `TaskController.list` instead of the built-in when
    `list[Task]` is inspected. Future annotations keep this controller signature
    safely resolvable during ToriPy route compilation.

## Step 5: Compose Modules and Bootstrap

Create `task_app/app.py`:

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/app.py"
```

The composition has three parts.

### CQRS Root

`CqrsModule.for_root(global_=True)` creates the command, query, and event buses
and exports them globally. The default uses three distinct process-local
`InMemoryTransport` instances. The application lifecycle starts and stops the
buses.

Global visibility is convenient for one application-wide CQRS graph. Keyed,
non-global roots can disambiguate bus access, but they do not partition automatic
discovery: each root can still see decorated handlers in the complete compiled
graph. Multiple graphs therefore need explicit bindings or otherwise
non-overlapping discovered registrations in addition to exact descriptor
resolution.

### Feature Module

`TasksModule` owns state, all five handlers, and the controller. The handlers do
not need to be exported. CQRS discovery reads provider metadata from the complete
compiled graph, including private feature providers.

State classes use explicit `ClassProvider` declarations. Handler classes can be
listed directly because their CQRS decorators also carry injectable provider
metadata.

At graph assembly, ToriPy CQRS verifies:

- valid registered command, query, and event handler metadata;
- no duplicate command or query handler for one registered message type;
- constructor dependencies and module visibility;
- valid singleton, request, and transient dependency paths.

Invalid or duplicate command/query registration fails before the server accepts
traffic. A completely missing command or query handler is detected when that
concrete message is dispatched, because an unregistered message type is not part
of the compiled handler inventory.

### HTTP Pipeline and Factory

`AppModule` owns the validation pipe and error filter. `PipelineOptions` installs
their tokens globally during compilation. `MsgspecValidationPipe` converts the
raw JSON body and path segment according to annotations; annotations alone do
not convert HTTP input.

`create_application()` compiles the graph with `StarletteAdapter` and returns an
unstarted application. The `asgi()` wrapper lets Uvicorn own startup and
shutdown through ASGI lifespan.

## Step 6: Run the Application

Start the development server from the project root:

```text
uv run tori-py run task_app.app:create_application
```

The CLI convenience command uses Uvicorn defaults. For host, port, reload,
workers, or proxy options, run the exported wrapper directly:

```text
uv run uvicorn task_app.app:application --lifespan on --reload
```

Create a task from another terminal:

=== "PowerShell"

    ```powershell
    '{"title":"  Learn CQRS with ToriPy  "}' |
      curl.exe -X POST "http://127.0.0.1:8000/tasks" `
        -H "content-type: application/json" `
        -H "x-actor: alice" `
        --data-binary '@-'
    ```

=== "Bash"

    ```bash
    curl -X POST "http://127.0.0.1:8000/tasks" \
      -H "content-type: application/json" \
      -H "x-actor: alice" \
      -d '{"title":"  Learn CQRS with ToriPy  "}'
    ```

The response is shaped like:

```json
{
  "task": {
    "id": 1,
    "title": "Learn CQRS with ToriPy",
    "created_by": "alice"
  },
  "projection": "asynchronous-in-process"
}
```

Read the projection:

```text
curl http://127.0.0.1:8000/tasks
curl http://127.0.0.1:8000/tasks/1
```

The first GET may race the event handler and temporarily return an empty list or
`404`. Repeating the request will normally observe the in-process projection,
but this demo provides no durable consistency deadline. A production API needs a
defined consistency contract, such as read-your-write from the write store,
bounded polling with an operation token, or a synchronous projection policy.

Try an invalid command:

```text
curl -X POST http://127.0.0.1:8000/tasks -H "content-type: application/json" -H "x-actor: alice" -d '{"title":"   "}'
```

The command handler raises `TaskTitleInvalid`, and the HTTP filter returns a
`400` Problem Details response. Stop the server normally so application
lifespan can drain and close CQRS resources.

## Step 7: Test Buses and HTTP

Create `task_app/test_app.py`:

```python
--8<-- "examples/tori_py/tutorials/cqrs_task_api/task_app/test_app.py"
```

Run it:

```text
uv run pytest task_app/test_app.py -q
```

Expected result:

```text
2 passed
```

The first test bypasses HTTP and verifies the application boundary directly:

1. Compile the production module graph through `TestingModule`.
2. Resolve the buses and feature-owned observer state.
3. Execute a command.
4. Wait for bounded projection and audit signals.
5. Drain already tracked event-handler tasks.
6. Execute queries and assert results.
7. Close the application in `finally`.

`EventBus.drain()` alone is not a queue barrier. Immediately after publication,
an event may still be queued with no handler task tracked. Waiting for an
application-level signal first proves that the expected handler reached its
effect; `drain()` then waits for tracked work within its timeout.

The second test sends real ASGI requests through the production controller,
validation pipe, filter, CQRS handlers, and application lifecycle. HTTPX uses an
in-process ASGI transport, so this test does not cover sockets, TLS, reverse
proxies, workers, or signal delivery.

## Understand the Runtime Flow

Application startup follows this shape:

```text
materialize CqrsModule
  -> compile providers and handler metadata
  -> build handler registry
  -> acquire three in-memory transports
  -> start event bus
  -> start query bus
  -> start command bus
  -> admit HTTP requests
```

One successful create request follows this shape:

```text
open HTTP request scope
  -> validate body and header
  -> controller calls CommandBus.execute(CreateTask)
  -> open independent CQRS command work scope
  -> resolve CreateTaskHandler and dependencies
  -> write TaskRepository
  -> EventBus.publish(TaskCreated) accepts event
  -> close command work scope
  -> return 202 response

event worker schedules both matching handlers
  +-> projection branch: independent work scope -> update TaskProjection -> close
  +-> audit branch: independent work scope -> append TaskAuditLog -> close
```

The event handlers may overlap. Registration determines scheduling order, not
start order or completion order.

The HTTP and CQRS work scopes are intentionally independent. Context variables,
request-scoped providers, and managed resources from the HTTP request do not
leak into command or event handlers. Copy safe application data, such as the
actor identifier, into the command explicitly.

During graceful shutdown, ToriPy closes normal request admission, then stops
commands, queries, and events under one decreasing shutdown budget. Accepted
commands can still query or publish while downstream buses remain available.

## What This Application Guarantees

The tutorial demonstrates these application behaviors:

- handlers are discovered only from explicitly compiled providers;
- commands and queries have one exact handler;
- one event fans out to both projection and audit effects;
- command and query results are statically typed;
- HTTP remains an adapter around buses;
- lifecycle starts, drains, and closes the in-memory CQRS graph;
- tests can exercise buses without HTTP and HTTP without a network socket.

Independent CQRS invocation scopes are an integration contract covered by the
`tori-py-cqrs` test suite. This compact tutorial configures request and transient
handler scopes but does not instrument provider identities merely to re-prove
the container contract.

It deliberately does not provide:

- durable task storage or projection checkpoints;
- atomic repository writes and event publication;
- retries, acknowledgements, dead letters, or event replay;
- command idempotency or exactly-once execution;
- authentication or trustworthy actor identity;
- cross-process messaging or distributed transactions;
- a guarantee that a timed-out command did not complete.

The included transport is process-local and at-most-once. Restarting the process
loses tasks, projections, audit entries, and queued events. Do not replace it
with a broker without first defining serialization, deadlines, settlement,
idempotency, and failure reconciliation.

## Exercises

Use these changes to verify your understanding:

1. Add `CompleteTask(Command[Task])` and a matching command handler.
2. Publish `TaskCompleted` and update the projection through a new event handler.
3. Add a second audit handler and observe independent fan-out.
4. Register two handlers for `CreateTask` and inspect the startup failure, then
   remove the duplicate.
5. Replace `TaskRepository` with an exported provider and override it through
   `TestingModule`.
6. Add OpenAPI metadata without changing command or query handlers.

## Next Steps

Read [CQRS Core](../techniques/cqrs/core.md) for envelopes, timeouts,
capacity, transport lifecycle, event task tracking, and command reentrancy.
Read [CQRS with ToriPy](../techniques/cqrs/tori-py.md) for explicit bindings,
multiple keyed graphs, invocation interceptors, and completion mapping.

When task history itself should be the source of truth, continue with
[Event Sourcing](../techniques/event-sourcing/index.md). Event sourcing is not a
required next stage for every CQRS application; ordinary transactional
persistence is often the smaller correct design.
