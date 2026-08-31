# Core Fundamentals

ToriPy makes application composition explicit. A root module identifies every
module reachable by the application; each module owns provider declarations and
controllers; exports define which provider tokens cross module boundaries. The
framework compiles that information once, then starts and shuts down the
resulting application under a deterministic lifecycle.

If you are coming from NestJS or FastAPI, start with the
[Concepts Map](../concepts-map.md) for direct terminology and behavior mappings.

## Minimal Application Shape

The complete tested provider example is included below. It shows the essential
path from a provider declaration to a controller dependency and an async
application factory.

```python
--8<-- "examples/tori_py/getting_started/first_provider/app.py"
```

Run the example from the repository root:

```text
uv run tori-py run examples.tori_py.getting_started.first_provider.app:create_application
```

`NestApplication.create()` returns an unstarted application. The CLI and ASGI
wrapper own `start()` and `shutdown()` through the ASGI lifespan.

## Composition in Five Steps

1. **Declare providers.** Use `@injectable()` as class self-token shorthand or
   use an explicit value, class, factory, or alias declaration.
2. **Declare modules.** List imports, providers, controllers, and exports. ToriPy
   does not scan packages or maintain a process-global registry.
3. **Compile.** Await `NestApplication.create()`. Deferred modules materialize,
   annotations are inspected, visibility is resolved, and dependency/scope
   paths are validated. Provider constructors do not run yet.
4. **Start.** The lifespan owner eagerly creates singleton providers and
   controllers, enters managed singleton resources, runs initialization hooks,
   and binds the selected adapter before requests are accepted.
5. **Shut down.** New requests stop, participants quiesce, active request/work
   scopes drain, hooks run in reverse ownership order, and resources close LIFO
   within one configured deadline.

## Guarantees at a Glance

| Area | Guarantee |
| --- | --- |
| Registration | Modules, providers, controllers, and imports are explicit |
| Compilation | Provider annotations are inspected once and frozen into an immutable graph |
| Visibility | Local provider, then direct imported export, then global export; same-level ambiguity is an error |
| Scope safety | No singleton may reach a request-scoped provider through any dependency path |
| Singleton startup | Singleton providers and controllers are eager, so startup failures are deterministic |
| Request isolation | Request providers are cached once per accepted HTTP request or explicit work scope |
| Resource ownership | Context managers are entered before exposure and closed once in reverse acquisition order |
| Shutdown | One monotonic deadline bounds quiescence, draining, cancellation observation, hooks, and cleanup |
| Introspection | Discovery reads immutable compiled views and never scans packages or constructs scoped providers |

## Failure Phases

Knowing when a failure occurs is important for operations and tests.

| Phase | Representative failures | Side effects |
| --- | --- | --- |
| Declaration | Invalid token, scope, metadata target, or duplicate decorator | The declaration is rejected immediately |
| Application creation | Module cycle, invalid export, unresolved/ambiguous dependency, provider cycle, scope violation | Deferred module factories may have run; provider constructors/resources/hooks have not |
| Startup | Provider construction, resource entry, lifecycle hook, or adapter binding failure | Completed startup work is rolled back in reverse order; state becomes `FAILED` |
| Request/work scope | Scoped construction or resource failure | Resources acquired by that scope unwind LIFO |
| Shutdown | Hook timeout/failure, cleanup failure, lingering task/resource | Remaining cleanup continues where safe; the first failure is returned and the application reaches `STOPPED` |

`diagnostic_code` and immutable diagnostic details belong specifically to
`ToriPyError` and its subclasses. Tests for those failures should prefer stable
codes over matching complete messages. HTTP behavior should instead assert the
status, safe Problem Details fields, and required headers. Cancellation tests
should assert `asyncio.CancelledError` propagation and cleanup behavior, not a
diagnostic code. `HttpException` and cancellation exceptions are not
`ToriPyError` values and do not expose `diagnostic_code`.

## Guide Order

1. [Modules](modules.md) explains composition, exports, globals, and dynamic
   identity.
2. [Providers and DI](providers-and-di.md) covers provider forms, tokens, and
   annotation rules.
3. [Scopes and Resources](scopes-and-resources.md) defines lifetime, ownership,
   work scopes, and context-manager cleanup.
4. [Lifecycle](lifecycle.md) gives the exact startup, rollback, and bounded
   shutdown sequence.
5. [Discovery and Reflection](discovery-and-reflection.md) covers typed metadata
   and read-only integration introspection.

## Testing and Production

`TestingModule` compiles and starts the same production application kernel after
applying explicit pre-compilation overrides. Close every testing application so
normal hooks and managed resource cleanup run:

```python
from tori_py.testing import TestingModule

from myapp.modules import AppModule


async def test_application_starts() -> None:
    application = await TestingModule.create(AppModule).compile()
    try:
        assert application.graph.root.module is AppModule
    finally:
        await application.close()
```

This focused test pattern is grounded in the framework testing suite. In HTTP
tests, prefer `TestingApplication.http_client()` so requests use the production
adapter, request scope, pipeline, and cleanup path.

In production, export an async factory and let exactly one ASGI lifespan owner
start and stop each application instance. Do not construct a started application
at import time, retain request resolvers in detached tasks, or catch bootstrap
errors to serve a partially initialized graph.

## Related APIs

- Application: `NestApplication`, `ApplicationOptions`, `ApplicationState`
- Composition: `module`, `ModuleSpec`, `DeferredModule`, `CompiledGraph`
- Providers: `injectable`, `ValueProvider`, `ClassProvider`, `FactoryProvider`,
  `AliasProvider`, `Inject`, `Scope`
- Scoped work: `ScopedResolver`, `WorkScopeFactory`
- Introspection: `Reflector`, `ModulesContainer`, `DiscoveryService`
- Testing: `TestingModule`, `TestingApplication`

## Next Steps

Read [Modules](modules.md), then [Providers and DI](providers-and-di.md). The
[First Application](../getting-started/first-application.md) remains the shortest
route to a running HTTP service.
