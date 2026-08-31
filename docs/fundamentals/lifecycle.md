# Application Lifecycle

The ToriPy lifecycle turns an immutable compiled graph into a running
application and then tears it down in reverse ownership order. It coordinates
module instances, singleton providers/controllers, driver binding, request/work
admission, cancellation, hooks, and managed resources under one state machine.

## Creation Is Not Startup

An async application factory should return an unstarted application:

```python
from tori_py import NestApplication, module
from tori_py.starlette import StarletteAdapter, asgi


@module()
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(
        AppModule,
        adapter=StarletteAdapter(),
    )


application = asgi(create_application)
```

`NestApplication.create()` materializes deferred modules, compiles and validates
the graph, validates adapter plans, and returns state `ApplicationState.COMPILED`.
It does not construct providers, enter provider resources, run hooks, bind the
driver, or accept work.

The ASGI wrapper awaits the factory once during lifespan startup, calls
`start()`, and delegates HTTP or WebSocket scopes only after startup succeeds. During lifespan
shutdown it calls `shutdown()`. A stopped or failed application instance cannot
restart; a server restart needs a newly created instance.

Use the CLI or an ASGI server through `uv`:

```text
uv run tori-py run myapp:create_application
uv run uvicorn myapp:application
```

## State Machine

```text
COMPILED -> STARTING -> STARTED -> STOPPING -> STOPPED
                    \-> FAILED
```

| State | Meaning |
| --- | --- |
| `COMPILED` | Graph and adapter plans exist; runtime resources are unopened |
| `STARTING` | Modules/singletons/resources/hooks/adapter are being started |
| `STARTED` | Normal request and work admission is open |
| `STOPPING` | Request admission is closed and one shared shutdown is running |
| `STOPPED` | Shutdown finished, including a bounded failure path |
| `FAILED` | Startup failed and rollback was attempted |

Invalid transitions raise `ApplicationStateError`. Calling `shutdown()` again
after `STOPPED` is a no-op. Concurrent callers during `STOPPING` join the same
shielded cleanup task.

## Lifecycle Hooks

Modules and eagerly created singleton provider/controller values may implement
these methods by name:

| Hook | Signature | Purpose |
| --- | --- | --- |
| `on_module_init` | `async def on_module_init(self) -> None` | Initialize after every singleton has been constructed |
| `on_application_bootstrap` | `async def on_application_bootstrap(self) -> None` | Start application-facing work after driver binding and work admission |
| `on_application_quiesce` | `async def on_application_quiesce(self, context: ShutdownContext) -> None` | Stop subsystem intake and drain owned work before work admission closes |
| `on_application_shutdown` | `async def on_application_shutdown(self) -> None` | Stop a successfully bootstrapped participant |
| `on_module_destroy` | `async def on_module_destroy(self) -> None` | Tear down a successfully module-initialized participant before resource exit |

Hooks must be asynchronous. All hooks except quiescence accept only bound
`self`; quiescence accepts exactly one `ShutdownContext`. The context's
`remaining()` method reports the remaining graceful quiescence budget.

A focused declaration looks like this:

```python
from tori_py import ClassProvider, ShutdownContext, module


class DeliveryConsumer:
    async def on_module_init(self) -> None:
        ...

    async def on_application_bootstrap(self) -> None:
        ...

    async def on_application_quiesce(
        self,
        context: ShutdownContext,
    ) -> None:
        remaining = context.remaining()
        ...

    async def on_application_shutdown(self) -> None:
        ...

    async def on_module_destroy(self) -> None:
        ...


@module(providers=[ClassProvider(DeliveryConsumer)])
class DeliveryModule:
    pass
```

Do not use a lifecycle hook instead of a context manager for a resource that can
follow `__aenter__`/`__aexit__`. Managed resources receive automatic LIFO
ownership and partial-startup rollback. Hooks are appropriate for subsystem
coordination, intake gates, and behavior that spans more than one resource.

## Exact Startup Order

Startup receives an already compiled graph and performs these steps:

1. Transition from `COMPILED` to `STARTING`.
2. Instantiate every module class with no arguments in dependency-first compiled
   module order.
3. Run `GraphValidator.validate_graph()` for module instances that implement the
   protocol, before singleton/resource startup.
4. Eagerly construct every singleton provider and controller in topological
   dependency order. Declaration order breaks ties between independent
   providers.
5. Enter each managed singleton resource before exposing its entered value to a
   dependent provider.
6. Call `on_module_init()` on module instances in compiled order.
7. Call `on_module_init()` on singleton provider/controller values in provider
   order.
8. Mark driver binding attempted and await the adapter binder.
9. Open work-scope admission.
10. Call `on_application_bootstrap()` on initialized modules, then singleton
    provider/controller values, preserving startup order.
11. Open normal request admission and transition to `STARTED`.

Controllers are singleton providers, so route binding receives started
controller instances. A startup failure is visible before normal traffic is
accepted.

## Startup Rollback

If singleton construction, resource entry, a hook, graph validation, or adapter
binding fails, ToriPy preserves the primary failure and rolls back completed work:

1. Close normal request admission.
2. Quiesce only participants whose bootstrap phase completed, in reverse order,
   while work scopes remain available.
3. Close work admission and drain active request/work scopes within the shutdown
   budget.
4. Call `on_application_shutdown()` only for successfully bootstrapped
   participants, in reverse order.
5. Close the adapter binder if binding was attempted, including a partial bind
   failure.
6. Call `on_module_destroy()` only for successfully initialized participants,
   in reverse order.
7. Close application-owned resources LIFO.
8. Log secondary rollback failures and finish in `FAILED`.

A participant is tracked only after its hook completes successfully. For
example, a provider whose `on_module_init()` raises does not later receive
`on_module_destroy()`, while participants initialized before it do.

Adapter binders are expected to make partial binding observable and implement
idempotent `close()`. ToriPy marks the attempt before awaiting `bind()`, so
rollback closes any partially created driver state.

## Exact Shutdown Order

Normal shutdown reverses startup ownership:

1. Transition to `STOPPING` and close normal request admission.
2. Call `on_application_quiesce(context)` in reverse bootstrap order while new
   work scopes remain admissible.
3. Close work-scope admission.
4. Wait for active request/work scope owners until the reserved drain cutoff.
5. Mark remaining leases closing, cancel unfinished owner/user tasks, and wait
   up to the configured cancellation grace capped by the shared deadline.
6. Call `on_application_shutdown()` on bootstrapped singleton values, then
   modules, in reverse order.
7. Close the attempted adapter binding exactly once.
8. Call `on_module_destroy()` on initialized singleton values, then modules, in
   reverse order.
9. Close application-owned resources in strict LIFO acquisition order.
10. Observe and log tasks, resources, and sync workers still active at the
    deadline; transition to `STOPPED`.

Request/work scope resources close before singleton resources because each scope
normally exits while draining. ToriPy never deliberately races a request
resource exit against code still using it. A cancellation-resistant task can
therefore leave a scoped resource open past the deadline; the framework logs the
leak rather than claiming unsafe cleanup.

The first shutdown failure is retained while later cleanup continues where safe.
One exception is a quiescence hook that ignores cancellation beyond its reserved
grace: ToriPy closes admission and drains tracked scopes, then deliberately
skips binder/provider teardown to avoid destroying resources under the still
running hook. This condition is logged as `lifecycle.lingering_task` and public
shutdown fails.

## Shutdown Budgets

`ApplicationOptions` controls one shared monotonic deadline:

```python
from tori_py import ApplicationOptions, NestApplication


options = ApplicationOptions(
    shutdown_timeout=30.0,
    cancellation_grace=1.0,
    cleanup_reserve=5.0,
)

application = await NestApplication.create(AppModule, options=options)
```

| Option | Default | Meaning |
| --- | --- | --- |
| `shutdown_timeout` | `30.0` | Total time available to public shutdown |
| `cancellation_grace` | `1.0` | Maximum reserved wait to observe cancelled scope/quiesce tasks |
| `cleanup_reserve` | `5.0` | Time held back from normal draining for hooks, binder close, and resources |

For the bounded-shutdown guarantee, all values must be finite, non-negative
numbers, excluding booleans, and `cancellation_grace + cleanup_reserve` cannot
exceed `shutdown_timeout`. The current validator enforces the numeric,
non-negative, and sum constraints but does not yet reject every non-finite
value: `float("nan")` and positive infinity can pass validation. This is a
validation gap, not support for non-finite budgets; either value invalidates the
bounded guarantee and must not be configured.

The drain cutoff is:

```text
shutdown deadline - cancellation grace - cleanup reserve
```

The options reserve time; they do not make an uncooperative task or operating
system thread terminable. Shutdown returns after the deadline without starting
unbounded background cleanup.

## Failure and Cancellation Behavior

| Situation | Public behavior |
| --- | --- |
| Start outside `COMPILED` | `ApplicationStateError` |
| Shutdown outside `STARTED`, `STOPPING`, or `STOPPED` | `ApplicationStateError` |
| Sync hook or invalid hook signature | `LifecycleError` with `lifecycle.startup_error`; startup rolls back or shutdown records the error |
| Hook/provider/resource/adapter startup exception | Original exception propagates after rollback; state is `FAILED` |
| Shutdown operation exceeds deadline | First `TimeoutError` propagates after bounded cleanup; state is `STOPPED` unless startup rollback ended `FAILED` |
| One concurrent shutdown caller is cancelled | Its cancellation propagates, but shielded shared cleanup continues; another caller can await it |
| Scope owner ignores cancellation | ToriPy logs lingering task/resource diagnostics and does not exit the resource concurrently |
| Sync exit worker exceeds deadline | The worker cannot be killed; it is observed and logged without a second exit attempt |

Do not catch lifecycle failures to mark an application ready. Startup is
failure-atomic only to the extent external resources and adapter binders honor
their own close contracts.

## Manual Lifecycle

Non-ASGI applications may explicitly start and stop a driver-neutral application:

```python
from tori_py import NestApplication


application = await NestApplication.create(AppModule)
await application.start()
try:
    ...
finally:
    await application.shutdown()
```

Do not omit the `finally`. HTTP applications should normally let `asgi()` or
`tori-py run` own this sequence so server readiness and framework state cannot
diverge.

## Testing Lifecycle

`TestingModule.compile()` compiles **and starts** a production-equivalent
application. `TestingApplication.close()` uses normal bounded shutdown.

This focused pattern is grounded in the lifecycle tests:

```python
from tori_py import ClassProvider, module
from tori_py.testing import TestingModule


events: list[str] = []


class Service:
    async def on_module_init(self) -> None:
        events.append("service-init")

    async def on_module_destroy(self) -> None:
        events.append("service-destroy")


@module(providers=[ClassProvider(Service)])
class AppModule:
    async def on_module_init(self) -> None:
        events.append("module-init")

    async def on_module_destroy(self) -> None:
        events.append("module-destroy")


application = await TestingModule.create(AppModule).compile()
try:
    assert events == ["module-init", "service-init"]
finally:
    await application.close()

assert events == [
    "module-init",
    "service-init",
    "service-destroy",
    "module-destroy",
]
```

For startup-failure tests, assert the primary exception, final application-side
effects, reverse hook/resource events, and stable diagnostic codes. Avoid sleeps;
use `asyncio.Event` to control cancellation and deadlines.

```text
uv run pytest packages/tori-py/tests/test_runtime_lifecycle.py packages/tori-py/tests/test_application.py
```

## NestJS and FastAPI Differences

For NestJS users, hook intent is familiar, but ToriPy hooks are async snake-case
methods and are validated at runtime startup. ToriPy adds an explicit
`on_application_quiesce(ShutdownContext)` phase, separate request/work admission
gates, and one bounded deadline. There is no separate signal-hook enablement in
the core lifecycle; the ASGI server owns process signals and lifespan.

For FastAPI users, `asgi(create_application)` fills the same process-boundary
role as an application lifespan, but ToriPy also starts every singleton provider,
runs provider/module hooks, and owns provider context managers. Route-level
dependency cleanup is not the application lifecycle.

## Production Notes

- Export an async factory, not a started global `NestApplication`.
- Let one lifespan owner control each application instance.
- Keep hooks cancellation-cooperative and regularly await while draining.
- Stop subsystem intake in quiescence; use available work scopes only to finish
  already accepted work.
- Size shutdown options from measured drain and cleanup behavior, then configure
  the process manager's termination grace above the framework timeout.
- Treat lingering diagnostics as resource-safety incidents, not harmless timeout
  noise.
- Use managed context managers for resource ownership and hooks for coordination.

## Related APIs

- Application: `NestApplication`, `ApplicationState`, `ApplicationOptions`
- Protocols: `ShutdownContext`, `GraphValidator`, `ApplicationAdapter`,
  `ApplicationBinder`, `ApplicationRuntime`
- Failures: `ApplicationStateError`, `LifecycleError`, `ResourceError`
- ASGI: `StarletteAdapter`, `asgi`
- Testing: `TestingModule`, `TestingApplication.close()`

## Next Steps

Review [Scopes and Resources](scopes-and-resources.md) for request/work draining
and cleanup outcomes. Read [Discovery and Reflection](discovery-and-reflection.md)
when a lifecycle-managed integration must enumerate providers during bootstrap.
