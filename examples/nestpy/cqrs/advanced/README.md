# Advanced Nestpy CQRS Task API

This reference application demonstrates the `nestpy-cqrs` discovery model and
scope behavior in one runnable HTTP service:

- command, query, and event handler classes are registered once as providers;
- `CqrsModule.for_root()` discovers their combined Nestpy-CQRS decorators
  automatically;
- handlers remain private to `TasksModule` and are not exported;
- each command gets a request-scoped handler and managed `CommandScope`;
- `TaskCreated` fans out to a request-scoped projection handler and a transient
  audit handler;
- transient query handlers read an asynchronously updated in-process projection;
- CQRS buses are global providers used by both controllers and handlers;
- HTTP validation and domain errors stay outside the CQRS core.

There is intentionally no `handlers=[...]` list:

```python
@command_handler(CreateTask, scope=Scope.REQUEST)
class CreateTaskHandler:
    ...


@module(providers=[CreateTaskHandler])
class TasksModule:
    pass


cqrs_module = CqrsModule.for_root(global_=True)
```

Run the application:

```text
uv run nestpy run examples.nestpy.cqrs.advanced.app:create_application
```

Create a task:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/tasks" -H "content-type: application/json" -H "x-actor: alice" -d "{\"title\":\"Study scoped CQRS\"}"
```

Read the projection:

```powershell
curl.exe "http://127.0.0.1:8000/tasks"
```

The command writes to `TaskRepository` and then publishes `TaskCreated`. Those
operations are not atomic. Delivery is non-durable, at-most-once, and has no
retry, so enqueue failure, process loss, or handler failure can leave the write
model and projection permanently divergent. This is an asynchronous in-process
projection, not a production eventual-consistency guarantee.

`EventBus.drain()` is not a transport barrier. The example tests first wait on
bounded projection/audit signals proving that the transport dequeued the event,
then call `drain()` to verify that no tracked handler work remains.

HTTP assertions use `TestingApplication.http_client()`, which supplies an
`httpx.AsyncClient` backed by `ASGITransport`, instead of manually constructing
ASGI scopes and messages. `TestingModule.compile()` already starts the
application lifecycle; the test closes it through `TestingApplication`.

The repository and projection are intentionally in-memory. Durable persistence,
transactions, durable messaging, retries, outbox delivery, authentication, and
authorization remain application concerns.
