# Scopes and Resources

Scopes answer two separate questions: how often is a provider value created, and
which lifetime owns its cleanup? ToriPy applies the same rules to HTTP requests
and explicit non-HTTP work, so scoped dependencies do not need transport-specific
container behavior.

## Scope Matrix

| Scope | Creation and cache | Resource owner | Typical use |
| --- | --- | --- | --- |
| `Scope.SINGLETON` | One eager value per application | Application | Stateless services, shared clients, configuration |
| `Scope.REQUEST` | One lazy value per accepted HTTP request or work scope | That request/work scope | Sessions, units of work, request identity |
| `Scope.TRANSIENT` | A new value for every resolution | Current application/request/work owner | Small per-consumer helpers or independently owned operations |

`ValueProvider` is singleton-only. `AliasProvider` inherits the target's
effective scope and canonical identity. Controllers are always singleton
providers.

A transient is new per **resolution**, not per method call. If one is injected
while constructing a singleton, that one transient value is retained by the
singleton and its resource belongs to the application. If it is resolved twice
inside a request, two values are created and both belong to that request.

## Scope Safety

The compiler validates every transitive dependency path. A singleton cannot
depend on a request provider directly, through a transient, or through an alias:

```text
singleton -> request                         invalid
singleton -> transient -> request            invalid
request   -> singleton                        valid
request   -> transient -> singleton           valid
transient resolved for request -> request     valid
```

An invalid path fails application creation with
`provider.scope_violation`. Diagnostic details include the complete provider and
scope path.

This rule prevents a long-lived object from retaining state owned by a completed
request. A singleton controller therefore cannot constructor-inject a
request-scoped provider. Resolve request state in an HTTP handler through an
`Inject` binding, or open an explicit work scope from a singleton coordinator.

## Explicit Work Scopes

`WorkScopeFactory` is an intrinsic dependency bound to the receiving provider's
exact compiled `ModuleId`. It lets singleton application services execute
non-HTTP operations with request-scope caching and cleanup.

The following focused example mirrors the runtime work-scope tests:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from tori_py import (
    ClassProvider,
    FactoryProvider,
    Scope,
    ScopedResolver,
    WorkScopeFactory,
    module,
)


@asynccontextmanager
async def session() -> AsyncIterator[str]:
    yield "request-owned session"


class ReportRunner:
    def __init__(self, scopes: WorkScopeFactory) -> None:
        self.scopes = scopes

    async def run(self) -> str:
        async def operation(resolver: ScopedResolver) -> str:
            value = await resolver.resolve("session")
            assert isinstance(value, str)
            return value

        return await self.scopes.run(operation)


@module(
    providers=[
        ClassProvider(ReportRunner),
        FactoryProvider("session", session, scope=Scope.REQUEST),
    ],
)
class ReportsModule:
    pass
```

Each `run()` call opens and closes a fresh work scope. The operation receives a
narrow `ScopedResolver`; resolving `"session"` repeatedly inside that operation
returns the same request-scoped entered value.

`WorkScopeFactory` provides three public operations:

| Operation | Context behavior | Use |
| --- | --- | --- |
| `open()` | Opens a fresh work scope but preserves current `contextvars` | When the caller needs explicit context-manager control |
| `run(operation)` | Runs one fresh work scope in a new empty `contextvars.Context` | Default for background, message, command, or scheduled work |
| `run_in(module_id, operation)` | Same isolation, but resolves from an exact compiled module identity | Integrations executing a discovered provider |

Work scopes are application-tracked. They are admitted after adapter binding,
remain available during bootstrap and quiescence, and stop admitting new work
before teardown. Applications cannot declare or override `WorkScopeFactory`.

## Managed Provider Resources

When `manage=True` and a provider result implements a complete Python context
manager, ToriPy enters it before exposing it:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from tori_py import FactoryProvider, Scope, module


events: list[str] = []


@asynccontextmanager
async def connection() -> AsyncIterator[str]:
    events.append("enter")
    try:
        yield "connected"
    finally:
        events.append("exit")


@module(
    providers=[
        FactoryProvider(
            "connection",
            connection,
            scope=Scope.REQUEST,
        )
    ],
)
class DataModule:
    pass
```

Consumers receive `"connected"`, the result of `__aenter__`, not the manager
object returned by `connection()`. The scope retains the exit callback and calls
it exactly once.

Resource defaults are intentional:

- `ClassProvider` and `FactoryProvider` use `manage=True` by default.
- `ValueProvider` uses `manage=False`; use `manage=True` to transfer ownership of
  a preconstructed context manager to the application.
- `AliasProvider` has no `manage` setting and never owns a second exit.
- A managed result that is not a context manager behaves as an ordinary value.

Asynchronous `__aenter__` and `__aexit__` run in the application event loop.
Synchronous `__enter__` and `__exit__` are offloaded to a framework-owned
executor. Entry and exit are not guaranteed to run on the same worker thread;
thread-affine resources require an application-provided async wrapper.

## Ownership Rules

The active owner determines where entered resources are recorded:

| Resolution situation | Cache, when applicable | Cleanup point |
| --- | --- | --- |
| Singleton provider starts | Application cache | Application shutdown or startup rollback |
| Request provider resolves in HTTP | Request cache | HTTP request scope exit |
| Request provider resolves in work | Work cache | Work operation exit |
| Transient resolves while building singleton | No transient cache | Application shutdown/rollback |
| Transient resolves in request/work | No transient cache | Request/work scope exit |
| Nested transient resolves | No transient cache | Same owner as the parent construction |

Resources close in strict reverse acquisition order within their owner. The
container does not infer ownership from object type, garbage collection, or the
task that eventually happens to reference the object.

## Scope Closing and Stale Resolvers

A request/work resolver has an invalidatable lease:

```text
open -> closing -> closed
```

Open permits resolution. Closing and closed reject new resolution with
`ScopeClosedError`. Resolution already in progress is tracked; normal scope exit
waits for active resolver users before cancelling remaining in-flight
construction and closing resources.

Do not retain a request resolver, request context, entered scoped resource, or
request provider in detached tasks. After scope exit, stale resolution fails
deterministically rather than silently constructing a dependency against a dead
request.

## Exception-Aware Unwinding

Request and work resource cleanup preserves the operation outcome:

- Every exit receives the original body exception tuple.
- A clean exit preserves the original return value or body exception unchanged.
- A truthy context-manager exit is invalid; managed resources cannot suppress
  the body exception.
- Every exit is attempted in LIFO order even when an earlier exit fails.
- Ordinary cleanup failures are collected in `ScopeFinalizationError`, which
  exposes `body_error` and ordered `cleanup_errors`.
- Cancellation with cleanup failures raises `ScopeCancellationError`, an
  `asyncio.CancelledError` subtype that retains the original cancellation and
  cleanup failures.
- `KeyboardInterrupt` and `SystemExit` retain object identity; cleanup failures
  are logged and attached as exception notes.

If dependency construction fails after entering nested resources, those newly
acquired resources roll back immediately in reverse order. The construction
failure remains the body/primary failure unless cleanup also fails, in which
case the public finalization error retains both.

Application shutdown also continues LIFO cleanup after an exit failure and
preserves the first shutdown failure. Cleanup is bounded by the shared shutdown
deadline; ToriPy observes and logs work that cannot safely finish, but it cannot
terminate a cancellation-resistant coroutine or a running sync worker thread.

## Failure Behavior

| Error | When it occurs |
| --- | --- |
| `BootstrapError` with `provider.scope_violation` | Compiled singleton dependency path reaches request scope |
| `ScopeError` | A request provider is resolved without a request/work scope, a token is not visible, or a work scope uses an unknown module identity |
| `ScopeClosedError` | Resolution uses a closing/closed request or work lease |
| `ResourceError` | Resource stack/acquisition is invalid or an exit tries to suppress an outcome |
| `ScopeFinalizationError` | Ordinary request/work cleanup has one or more failures |
| `ScopeCancellationError` | Scope cancellation and cleanup failures must both be retained |

Check `cleanup_errors` in cleanup-focused tests. In application code, do not
catch `ScopeCancellationError` as an ordinary `Exception`; cancellation must
continue to propagate.

## Testing Scopes and Resources

Resolve a singleton work coordinator, run the public operation, and always close
the testing application:

```python
from tori_py.testing import TestingModule


application = await TestingModule.create(ReportsModule).compile()
try:
    runner = await application.resolve(ReportRunner)
    assert isinstance(runner, ReportRunner)
    assert await runner.run() == "request-owned session"
finally:
    await application.close()
```

For HTTP request scope, prefer `TestingApplication.http_client()` and assert
observable behavior across two requests. Do not call
`TestingApplication.resolve()` for a request-scoped token: that facade resolves
from application scope and correctly raises `ScopeError`.

Resource tests should assert entry/exit events and close in `finally`, including
when the operation under test fails.

```text
uv run pytest packages/tori-py/tests/test_runtime_lifecycle.py packages/tori-py/tests/test_resource_unwinding.py
```

## NestJS and FastAPI Differences

For NestJS users, scope names are familiar, but ToriPy does not bubble request
scope through a singleton graph or inject request proxies. The invalid path is a
compile-time error. `WorkScopeFactory` is the explicit way for a long-lived
provider to start isolated scoped work.

For FastAPI users, a ToriPy managed provider resembles a `yield` dependency only
at a high level. Its lifetime comes from the provider's declared scope, applies
outside HTTP, and participates in application startup/rollback/shutdown as well
as request cleanup. `Scope.TRANSIENT` is the explicit no-cache lifetime; ToriPy
does not use `Depends(..., use_cache=False)`.

## Production Notes

- Use async context managers for network/database resources, especially when
  thread affinity matters.
- Keep request resources inside the request or work operation; return data, not
  live scoped dependencies.
- Use `run()` rather than `open()` when background work must not inherit request
  IDs, logging context, or other ambient `contextvars`.
- Make resource exits idempotent at the application boundary even though ToriPy
  guarantees one framework-owned exit attempt.
- Monitor `resource.cleanup_error`, `resource.lingering_resource`,
  `resource.lingering_worker`, and `lifecycle.lingering_task` logs.
- Configure enough shutdown cleanup reserve for real resource exits; see
  [Lifecycle](lifecycle.md).

## Related APIs

- Scope: `Scope`, `ScopedResolver`, `QualifiedScopedResolver`,
  `WorkScopeFactory`, `RequestScope`
- Providers: `ClassProvider`, `FactoryProvider`, `ValueProvider`,
  `AliasProvider`
- Failures: `ScopeError`, `ScopeClosedError`, `ResourceError`,
  `ScopeFinalizationError`, `ScopeCancellationError`
- Lifecycle options: `ApplicationOptions`, `ShutdownContext`

## Next Steps

Read [Lifecycle](lifecycle.md) for startup resource acquisition, rollback, and
bounded shutdown. Integration authors should continue to
[Discovery and Reflection](discovery-and-reflection.md) for exact-module work
execution with `run_in()`.
