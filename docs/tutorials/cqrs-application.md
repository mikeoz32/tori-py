# CQRS Task Application

This tutorial follows the runnable application in
[`examples/tori_py/cqrs/advanced`](https://github.com/mikeoz32/tori-py/tree/main/examples/tori_py/cqrs/advanced).
It builds on Tori Py modules and HTTP while introducing `tori-py-cqrs` handler
discovery, independent handler scopes, event fan-out, and a separate read model.

## Prepare And Verify The Example

From the repository root:

```text
uv sync --all-packages --all-groups --extra cli
uv run pytest examples/tori_py/cqrs/advanced/test_example.py -q
```

Keep these files open while reading:

| File | Purpose |
| --- | --- |
| [`app.py`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py) | Messages, models, handlers, HTTP adapter, modules, and bootstrap |
| [`test_example.py`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/test_example.py) | Direct-bus and HTTP verification, including scope metrics and event completion |
| [`README.md`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/README.md) | Guarantees and deliberate non-goals |

## Start With The Message Flow

The write and read paths are deliberately different:

```text
POST /tasks
  -> CreateTask command
  -> CreateTaskHandler
  -> TaskRepository write model
  -> publish TaskCreated
       -> ProjectTaskCreated -> TaskProjection
       -> AuditTaskCreated   -> AuditLog

GET /tasks or /tasks/{id}
  -> ListTasks or GetTask query
  -> matching query handler
  -> TaskProjection read model
```

The HTTP controller translates requests to messages. The buses select handlers.
The command handler changes the write model; query handlers never read that
write repository. They read `TaskProjection`, which is updated by an event
handler.

## Define Transport DTOs And Application Messages

The source keeps the HTTP request body separate from CQRS messages:

| Type | Role |
| --- | --- |
| [`CreateTaskBody`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L50-L53) | Msgspec HTTP body converted by the validation pipe |
| [`CreateTask`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L71-L75) | Command carrying the requested title and actor into the application layer |
| [`GetTask` and `ListTasks`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L77-L84) | Query messages with typed result declarations |
| [`TaskCreated`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L87-L89) | Fact published for independent in-process reactions |
| [`Task`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L42-L47) | Immutable value returned by the command and materialized in the projection |

`Command[Task]` and `Query[Task]` or `Query[list[Task]]` document the value
returned by `execute()`. `Event` has no returned application result. The marker
types provide routing categories; they do not impose persistence or domain
modeling rules.

Immutable slotted dataclasses are used for CQRS messages, while msgspec structs
own HTTP and response conversion. CQRS core does not require msgspec, Pydantic,
Starlette, or Tori Py.

## Separate The Write And Read Models

[`TaskRepository`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L92-L103)
is the singleton write model. It allocates IDs and stores tasks, but exposes no
query API in this example.

[`TaskProjection`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L106-L133)
is a different singleton. It applies `TaskCreated`, serves sorted reads, and
offers a bounded `wait_for_count()` signal for deterministic tests. `AuditLog`
is another independent event-handler target. This fan-out demonstrates that one
fact may feed several local effects without coupling the command handler to
their implementations.

These are logical CQRS boundaries, not physical services. All three objects are
in the same process and all lose state on restart.

## Discover Handlers From The Module Graph

Handler decorators combine CQRS registration metadata with Tori Py injectable
metadata:

| Decorator | Handler | Scope |
| --- | --- | --- |
| `@command_handler(CreateTask)` | [`CreateTaskHandler`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L189-L215) | `REQUEST` |
| `@event_handler(TaskCreated)` | [`ProjectTaskCreated`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L218-L227) | `REQUEST` |
| `@event_handler(TaskCreated)` | [`AuditTaskCreated`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L230-L238) | `TRANSIENT` |
| `@query_handler(GetTask)` | [`GetTaskHandler`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L241-L250) | `TRANSIENT` |
| `@query_handler(ListTasks)` | [`ListTasksHandler`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L253-L262) | `TRANSIENT` |

Every decorated handler still appears once in `TasksModule.providers`.
[`CqrsModule.for_root(global_=True)` and the module graph](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L323-L353)
discover metadata from those compiled providers. There is no `handlers=[...]`
list, package scan, import side effect, or process-global registry. The handlers
remain private to `TasksModule`; they do not need to be exported.

Commands and queries require exactly one matching concrete-type handler. Events
may have zero or more. Duplicate command/query registrations fail graph
assembly rather than relying on registration order.

## Understand CQRS Work Scopes

`Scope.REQUEST` on a CQRS handler means one Tori Py work scope for one handler
invocation. It is not the surrounding HTTP request scope. Ambient HTTP request
context is not propagated into CQRS dispatch.

The command handler injects a request-scoped
[`CommandScope`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L167-L187).
Its async context manager records entry and exit. `ScopeMetrics` also records
handler construction counts, making lifecycle behavior observable without
inspecting the container.

For two direct commands, the test proves:

- two independent command work scopes enter and exit;
- two request-scoped command handlers are constructed;
- each projection event delivery constructs its own request-scoped handler;
- each query resolution constructs a transient handler;
- singleton repository, projection, audit log, and metrics state is reused by
  the application.

Each event handler gets an independent work scope. One event handler failing
does not share request-scoped resources with another event handler receiving the
same event.

## Follow The Command And Event Boundary

`CreateTaskHandler.handle()` strips the title, enforces the 1-120 character
rule, writes the task, publishes `TaskCreated`, and returns the task.

The crucial ordering is:

```text
repository write
  -> EventBus.publish() submits the event to the in-memory transport
  -> transport accepts the event and may schedule handlers immediately
  -> publish returns without waiting for projection or audit completion
  -> command handler returns Task
```

Handler scheduling may occur before or after `publish()` and the command return.
`publish()` completion is not projection completion. The controller therefore
returns `202` and explicitly labels the projection
`asynchronous-in-process`. A GET immediately following POST can observe the old
projection. The tests wait for bounded projection and audit signals before
asserting their effects.

The repository write and event publication are not atomic. If publication or a
handler fails, the write model and read model can diverge permanently. The
included in-memory event transport is process-local, non-durable, at-most-once,
and has no retry, acknowledgement, dead-letter, or replay mechanism.

## Keep HTTP At The Edge

[`TaskController`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L265-L297)
injects only `CommandBus` and `QueryBus`:

- `POST /tasks` converts `CreateTaskBody`, binds required `X-Actor`, creates a
  command, and returns its result with HTTP request metadata.
- `GET /tasks` executes `ListTasks`.
- `GET /tasks/{task_id}` executes `GetTask` after path conversion.

`RequestContext` stays in the controller. The actor string is copied explicitly
into `CreateTask`; the CQRS handler does not depend on an HTTP header or context.
The example does not authenticate that actor, so it must not be treated as a
trusted production identity.

[`TaskErrorFilter`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/app.py#L300-L320)
maps application failures to Problem Details. `PipelineOptions` installs HTTP
msgspec conversion and this filter during compilation. HTTP validation and
error rendering remain outside CQRS core.

## Run The HTTP Flow

Start the application:

```text
uv run tori-py run examples.tori_py.cqrs.advanced.app:create_application
```

Create and then read a task:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/tasks" -H "content-type: application/json" -H "x-actor: alice" -H "x-request-id: cqrs-tutorial" -d '{"title":"Study scoped CQRS"}'
curl.exe "http://127.0.0.1:8000/tasks"
curl.exe "http://127.0.0.1:8000/tasks/1"
```

If the first read races the projection, repeat it for this demonstration. A real
API must define a consistency contract instead of asking clients to poll without
a bound or token.

The application also exports an ASGI lifespan wrapper:

```text
uv run uvicorn examples.tori_py.cqrs.advanced.app:application --lifespan on
```

## Learn From The Tests

The [direct-bus test](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/test_example.py#L21-L60)
resolves the three buses and feature-owned singleton observers. It executes two
commands, waits on projection and audit conditions, calls `EventBus.drain()`,
executes queries, and verifies scope counts.

The [HTTP test](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/advanced/test_example.py#L63-L121)
proves that malformed input fails before CQRS dispatch, domain-invalid input
opens and closes a command scope, valid input returns `202`, asynchronous
effects become observable, queries read the projection, and missing tasks map to
`404`.

`EventBus.drain()` is not a transport-queue barrier. Immediately after
`publish()`, the event may still be queued and no handler task may yet be
tracked. The reliable test sequence for this transport is:

1. Publish through the application action.
2. Await a bounded application-level signal proving the expected handler was
   scheduled or produced its effect.
3. Call `drain()` with a sufficient timeout to await tracked handler work.
4. Assert the result and always close the testing application.

See [CQRS Core](../techniques/cqrs/core.md) for transport semantics and
[CQRS with Tori Py](../techniques/cqrs/tori-py.md) for discovery, scopes,
interceptors, and lifecycle.

## Current Boundaries

The advanced example does not provide durable persistence, atomic write/event
publication, retry, an outbox, command idempotency, durable projections,
authentication, authorization, or distributed messaging. A caller timeout does
not prove a command handler did not complete, so blindly retrying an effectful
command is unsafe.

CQRS itself does not require event sourcing. Use ordinary persistence when that
is the smaller correct model.

## Next Step: Event Sourcing

Continue to the tested
[`examples/tori_py/cqrs/event_sourcing`](https://github.com/mikeoz32/tori-py/tree/main/examples/tori_py/cqrs/event_sourcing)
project when the aggregate's ordered decision history should become the source
of truth.

Start with its
[`README.md`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/event_sourcing/README.md),
then inspect the
[`domain`](https://github.com/mikeoz32/tori-py/tree/main/examples/tori_py/cqrs/event_sourcing/domain),
[`application`](https://github.com/mikeoz32/tori-py/tree/main/examples/tori_py/cqrs/event_sourcing/application),
[`infrastructure`](https://github.com/mikeoz32/tori-py/tree/main/examples/tori_py/cqrs/event_sourcing/infrastructure),
and
[`test_event_sourcing_project.py`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/cqrs/event_sourcing/test_event_sourcing_project.py).

That project adds aggregates, stable event aliases and upcasting, expected stream
versions, automatic command Unit of Work boundaries, optimistic concurrency,
and projection catch-up from committed positions. It still uses
`InMemoryEventStore` and an in-memory projection, so it demonstrates semantics,
not production durability. Read the [Event Sourcing guide](../techniques/event-sourcing/index.md)
before adapting it to a durable store and outbox.
