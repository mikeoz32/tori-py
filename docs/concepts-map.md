# Concepts Map

ToriPy is built around one explicit application graph. Modules describe the
graph, provider declarations describe how values are created, scopes determine
who owns those values, and the application lifecycle determines when work may
start and when resources must close.

Use this page as a map before reading the detailed fundamentals guides.

## The Core Model

```text
root module
    |
    | imports modules and declares providers/controllers
    v
NestApplication.create()
    |
    | materializes deferred modules and compiles an immutable graph
    v
compiled application
    |
    | start: create singletons, enter resources, run hooks, bind adapter
    v
started application
    |
    | request scopes and explicit work scopes resolve scoped providers
    v
shutdown
    |
    | quiesce, drain scopes, run reverse hooks, close resources LIFO
    v
stopped application
```

Compilation and startup are deliberately separate. A declaration, visibility,
dependency-cycle, or scope-path error fails while creating the application,
before provider constructors or managed resources run. Provider construction,
resource acquisition, adapter binding, and lifecycle hook failures occur during
startup and trigger rollback.

## Vocabulary

| Concept | Meaning | Guide |
| --- | --- | --- |
| Module | An explicit composition boundary with imports, providers, controllers, exports, and optional global visibility | [Modules](fundamentals/modules.md) |
| Provider token | A class or non-empty string used as a dependency identity | [Providers and DI](fundamentals/providers-and-di.md) |
| Provider declaration | A value, class, factory, or alias registration owned by one module | [Providers and DI](fundamentals/providers-and-di.md) |
| Module visibility | The rule that a module sees local providers, direct imported exports, then global exports | [Modules](fundamentals/modules.md) |
| Scope | The lifetime of a provider: singleton, request, or transient | [Scopes and Resources](fundamentals/scopes-and-resources.md) |
| Managed resource | A provider result entered and exited through Python's sync or async context-manager protocol | [Scopes and Resources](fundamentals/scopes-and-resources.md) |
| Work scope | An application-tracked non-HTTP scope with request-scope DI semantics | [Scopes and Resources](fundamentals/scopes-and-resources.md) |
| Lifecycle participant | A module instance or eagerly created singleton provider/controller that may implement async hooks | [Lifecycle](fundamentals/lifecycle.md) |
| Reflection metadata | Typed metadata attached directly to a class or function without a global registry | [Discovery and Reflection](fundamentals/discovery-and-reflection.md) |
| Discovery | Read-only enumeration of the already compiled module/provider graph | [Discovery and Reflection](fundamentals/discovery-and-reflection.md) |
| Adapter | The explicit boundary that binds a driver, such as Starlette, to a compiled application | [Fundamentals](fundamentals/index.md) |

## Where Code Belongs

| You are defining... | Put it in... | Why |
| --- | --- | --- |
| A feature's use cases and policies | Providers in a feature module | Dependencies and visibility stay explicit |
| Infrastructure such as a repository or client | A provider owned by an infrastructure module | Resource ownership and test replacement have one composition boundary |
| An HTTP endpoint | A controller listed by its owning module | Controllers are discovered from the compiled graph, not package scans |
| Configuration reusable by several modules | An exported provider, often from a dynamic module | Configuration is materialized before runtime startup |
| Per-request or per-operation state | A request-scoped provider | The request/work scope owns caching and cleanup |
| Background or transport-delivered work | A singleton coordinator using `WorkScopeFactory` | Request dependencies do not escape an HTTP request |
| Integration metadata | A typed `MetadataDecorator` | Integrations can discover explicit declarations without importing application packages |

## NestJS Mapping

ToriPy keeps useful NestJS vocabulary but not NestJS internals.

| NestJS | ToriPy | Important difference |
| --- | --- | --- |
| `@Module()` | `@module()` | Module classes receive no constructor injection and exist only as composition/lifecycle participants |
| Provider token | Class or string token | No symbol token and no implicit class registration |
| `useValue` / `useClass` / `useFactory` / `useExisting` | `ValueProvider` / `ClassProvider` / `FactoryProvider` / `AliasProvider` | Declarations are frozen Python values compiled before startup |
| `@Inject()` | `Annotated[T, Inject(token)]` | Python annotations are inspected once during graph compilation |
| Singleton / request / transient scope | `Scope.SINGLETON` / `REQUEST` / `TRANSIENT` | A singleton-to-request dependency path is rejected at compilation rather than proxied |
| Dynamic module | `DeferredModule` returning `ModuleSpec` | Identity is explicit: `(module class, key)`; no configuration hashing |
| `DiscoveryService` / `ModulesContainer` | Same public concepts | Views are immutable; discovery cannot register or construct providers |
| Lifecycle hooks | Async methods with defined ToriPy names | ToriPy adds bounded quiescence and one shared shutdown deadline |

There is no equivalent of NestJS package scanning, `forwardRef()`, runtime module
mutation, or request-scoped proxy injection into singletons.

## FastAPI Mapping

FastAPI organizes most composition around path operations and callable
dependencies. ToriPy compiles an application-wide module and provider graph
before serving traffic.

| FastAPI | ToriPy | Important difference |
| --- | --- | --- |
| `APIRouter` inclusion | Module imports plus controller registration | Imports also define provider visibility; they are not only route grouping |
| `Depends(callable)` | Constructor/factory injection by provider token | Dependencies must be registered; arbitrary callables are not executed implicitly |
| Per-request dependency cache | Request-scoped provider cache | Scope is declared on the provider and also applies to non-HTTP work scopes |
| `yield` dependency | Managed provider context manager | Ownership follows application/request/transient scope and cleanup is LIFO |
| Application lifespan | `NestApplication` lifecycle plus adapter lifespan | Provider resources and hooks participate automatically in deterministic startup/rollback/shutdown |
| Route/dependency inspection | `DiscoveryService` over compiled providers/controllers | Discovery does not inspect arbitrary imported callables or scan packages |

ToriPy does not depend on FastAPI or Pydantic. The Starlette adapter is explicit,
and core modules, DI, scopes, and lifecycle remain transport-neutral.

## Choose a Starting Point

- New to ToriPy: read the [Fundamentals overview](fundamentals/index.md).
- Designing feature boundaries: read [Modules](fundamentals/modules.md).
- Registering application services: read [Providers and DI](fundamentals/providers-and-di.md).
- Managing sessions, clients, or background work: read [Scopes and Resources](fundamentals/scopes-and-resources.md).
- Operating startup and graceful shutdown: read [Lifecycle](fundamentals/lifecycle.md).
- Building an integration: read [Discovery and Reflection](fundamentals/discovery-and-reflection.md).

For a complete composed application, see the in-memory
[Task API](reference/task-api.md).
