# Background Work

Tori Py has no built-in job queue or background-work scheduler. It provides
application lifecycle, tracked work scopes, and optional message/stream
integrations. The application must choose who accepts work, who owns the task,
how shutdown drains it, and whether execution is durable.

## Do not escape request scope

Do not retain any of these after a request, CQRS invocation, message delivery, or
stream attempt ends:

- a request-scoped provider;
- `ExecutionContext`, `HttpContext`, or `RequestContext`;
- `context.resolver` or another scoped resolver;
- a repository tied to an invocation-local Unit of Work;
- an active SQLAlchemy transaction context.

Detached use is not made safe by Python `ContextVar` inheritance. Tori Py
invalidates the scope lease at completion, and SQLAlchemy guards transaction
state by owner task. Store an immutable job DTO containing only the minimized
identifiers and values needed to do later work.

Avoid this controller pattern:

```python
# Wrong: the task is unowned and captures request-lifetime state.
asyncio.create_task(request_repository.finish_later(task_id))
```

The application cannot reliably observe, drain, cancel, or report that task, and
the repository may already be closed when it runs.

## Run work in a fresh scope

A singleton may inject the intrinsic `WorkScopeFactory`. `run()` clears inherited
execution context, opens one application-tracked scope bound to the singleton's
exact module, and closes all scoped resources before returning:

```python
from dataclasses import dataclass
from typing import cast

from tori_py import WorkScopeFactory, injectable


@dataclass(frozen=True, slots=True)
class RebuildProjection:
    projection_id: str


@injectable()
class ProjectionExecutor:
    def __init__(self, scopes: WorkScopeFactory) -> None:
        self._scopes = scopes

    async def execute(self, job: RebuildProjection) -> None:
        async def operation(resolver) -> None:
            repository = cast(
                ProjectionRepository,
                await resolver.resolve(ProjectionRepository),
            )
            await repository.rebuild(job.projection_id)

        await self._scopes.run(operation)
```

`ProjectionRepository` may be request-scoped. It is created once in this work
scope and closed before `execute()` returns. Transient resources resolved by the
operation are owned by the same scope.

`open()` is available for explicit lexical control, but it controls DI lifetime
only and does not clear ambient context variables. Prefer `run()` for work that
must not inherit HTTP, logging, or message context. Integration authors may use
`run_in(module_id, operation)` with an exact compiled owner identity obtained
from public discovery plans.

`WorkScopeFactory` does not schedule, persist, retry, or deduplicate the job. A
caller can await `execute()` directly, or a separately owned consumer can invoke
it after accepting a job.

## Own intake and shutdown

An application-owned in-process worker must be an eager singleton lifecycle
participant and satisfy all of these requirements:

1. Keep a finite queue and reject or backpressure above its bound.
2. Create and retain every worker task; never fire and forget.
3. Record worker failure and expose degraded readiness.
4. Stop intake in `on_application_quiesce(context)`.
5. Drain accepted jobs only within `context.remaining()`.
6. Run each job through `WorkScopeFactory.run()`.
7. Cancel and await unfinished tasks at the cutoff.
8. Return from shutdown without starting detached cleanup.

Lifecycle hook names are `on_module_init()`,
`on_application_bootstrap()`, `on_application_quiesce(context)`,
`on_application_shutdown()`, and `on_module_destroy()`. Quiescence runs after
normal request admission closes but while work-scope admission remains open,
which is the intended drain window. The application must still implement queue,
task, error, and retry policy; Tori Py does not supply a worker base class.

If accepted work must survive process failure, an in-process queue is the wrong
boundary. Use an application-owned durable queue or one of the integrations
below and retain its delivery semantics.

## Starlette background responses

A native Starlette response may carry `starlette.background.BackgroundTask`.
Tori Py keeps the HTTP request scope open until the response ASGI call, including
the Starlette background task, finishes. This is a deliberate driver-specific
escape hatch:

```python
from starlette.background import BackgroundTask
from starlette.responses import Response


async def after_response(job: RebuildProjection) -> None:
    await executor.execute(job)


return Response(
    "accepted",
    status_code=202,
    background=BackgroundTask(after_response, job),
)
```

Pass an immutable job and a singleton executor, not a request-scoped repository
or context. Although the scope remains open during this response execution,
using fresh `WorkScopeFactory.run()` keeps later work independent and makes the
same executor usable outside HTTP.

This path is not portable to another Tori Py driver, is not durable, does not
provide retries, and delays completion of the ASGI response call and request
scope cleanup. A failure after headers begin cannot be converted by filters into
another response. `HttpResponse` intentionally has no background-task field.

## Existing durable delivery integrations

- `tori-py-microservices` provides RPC and queue-event delivery with in-memory
  and RabbitMQ transports. RabbitMQ execution is at least once; use finite RPC
  deadlines, stable idempotency, and application outbox/inbox policy.
- `tori-py-persistent-streams` processes replayable partitioned logs and advances
  a checkpoint only after handler and scope cleanup. Effects are at least once,
  and poison records stop their partition.
- `tori-py-cqrs` provides an in-process application bus and fresh work scopes.
  It is not a durable queue. Publishing a CQRS event is not an outbox.
- `CommandSynchronization.after_commit()` can trigger an in-process notification
  after event-store commit, but it is not crash-safe durable publication.

Do not automatically bridge package families. Translate an external DTO into an
application command or service call at an explicit adapter boundary.

## Testing

For a scoped executor:

- Register a request-scoped recording repository and invoke `execute()` twice.
- Assert two repository instances were created and each closed once.
- Set a request `ContextVar` before invocation and assert code inside
  `WorkScopeFactory.run()` does not observe it.
- Cancel the operation and assert cancellation remains cancellation while
  cleanup runs.

For an in-process worker:

- Use a finite queue and deterministic events instead of sleeps.
- Prove no intake is accepted after quiescence starts.
- Prove accepted work drains while work scopes are still available.
- Force the shutdown deadline and prove retained tasks are cancelled and joined.
- Force resource cleanup failure and assert the typed scope failure is observed.
- Close the `TestingApplication` and assert no worker tasks or resources remain.

For broker or persistent-stream workers, run deterministic in-memory tests for
application behavior and real infrastructure tests for topology, redelivery,
confirm/ACK uncertainty, retention, reconnect, TLS, and crash boundaries. Do not
interpret a passing in-memory test as a durability result.
