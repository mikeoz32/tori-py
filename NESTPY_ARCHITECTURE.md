# Nestpy Architecture Specification

Status: approved architecture baseline. Executable implementation contracts are
split into `spec/nestpy/phase-n0-*.md` through `phase-n7-*.md`. No Nestpy code
is implemented by this document.

## 1. Purpose

`nestpy` is a Python 3.14 application framework inspired by NestJS concepts:
modules, providers, controllers, lifecycle, and a composable HTTP pipeline. It
is not a TypeScript/NestJS port and must not reproduce NestJS internals where
Python has a clearer model.

The first product is a Starlette-backed HTTP application framework with a
Python-native DI container. It provides:

- explicit module composition;
- explicit providers with annotation-based constructor resolution;
- singleton, request, and transient scopes;
- resource and application lifecycle;
- controller decorators and typed HTTP binding;
- middleware, guards, pipes, interceptors, and filters;
- settings, logging, request IDs, and testing overrides.

`cqrs-core` remains framework-agnostic and Nestpy does not depend on it. The
implemented optional `nestpy-cqrs` package bridges Nestpy DI/lifecycle to CQRS
buses without creating a reverse dependency.

## 2. Scope and Non-Goals

### 2.1 v1 goals

Nestpy v1 MUST provide:

- a root module and async application factory;
- static modules and deferred async dynamic modules;
- explicit imports/providers/exports/controllers and opt-in global modules;
- class and string tokens;
- value, class, factory, and alias providers;
- singleton, request, and transient scopes;
- synchronous context-manager resources through executor offload and native
  asynchronous context-manager resources;
- module and singleton lifecycle hooks;
- Starlette as the sole HTTP driver;
- controllers, route decorators, annotated input binding, dataclass/JSON output;
- global/controller/route middleware, guards, pipes, interceptors, and filters;
- Problem Details errors;
- TOML, JSON, YAML, dotenv, environment, and CLI settings sources;
- logger protocol and request ID correlation;
- testing modules and public provider overrides;
- ASGI export plus a CLI.

### 2.2 Explicit non-goals

Nestpy v1 MUST NOT provide:

- FastAPI support or FastAPI runtime dependencies;
- package scanning, provider auto-registration, or process-global registries;
- automatic module re-exporting;
- WebSocket, template, static-file, or framework-managed streaming APIs;
- authentication, CORS, CSRF, rate-limiting, or security-header policies;
- Pydantic dependency or integration requirement;
- OpenTelemetry dependency;
- CQRS dependency or built-in CQRS integration;
- database, ORM, broker, job queue, or background-work framework.

Starlette `Response` subclasses remain a deliberate escape hatch. This permits
an application to use advanced Starlette behavior, including streaming or
background tasks, but Nestpy does not add first-class APIs, validation, or
portability guarantees for those capabilities in v1.

## 3. Workspace and Dependencies

Nestpy becomes a standalone workspace package:

```text
packages/nestpy/
  src/nestpy/
    application.py
    core/
    http/
    starlette/
    settings/
    testing/
    cli/
```

The public package is one distribution with layered subpackages:

```text
nestpy.core       No Starlette imports.
nestpy.application Depends only on core and owns the public application shell.
nestpy.http       Depends on core/msgspec and owns HTTP execution semantics.
nestpy.settings   Depends on core and msgspec, never Starlette.
nestpy.starlette  Adapts nestpy.http to ASGI and native Starlette objects.
nestpy.testing    Depends on application/core and optional adapters.
nestpy.cli        Depends on the Starlette driver and server integration.
```

Dependency policy:

- `starlette` and `msgspec` are required dependencies of the v1 `nestpy`
  distribution.
- `PyYAML` is an optional `settings-yaml` extra. Selecting a YAML source
  without that extra is a clear bootstrap error.
- `uvicorn` is an optional `cli` extra. It is the only v1 server used by
  `nestpy run`; the command fails with an actionable install message when the
  `cli` extra is absent.
- `dependency_injector`, FastAPI, and Pydantic are not Nestpy dependencies.

`nestpy.core` MUST be importable without loading Starlette symbols, although
the installed v1 distribution includes Starlette for its first driver.

The console-script entry point is `nestpy = nestpy.cli:main`. It imports
Uvicorn lazily only for the `run` command, so importing `nestpy` or using a
non-server command never imports a server implementation.

## 4. Bootstrap and ASGI Lifecycle

### 4.1 Async factory export

An application exports an async factory:

```python
from nestpy import NestApplication
from nestpy.starlette import StarletteAdapter


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())
```

`NestApplication` is driver-neutral and owned by `nestpy.application`.
`NestApplication.create()` performs asynchronous graph compilation and adapter
preparation only:

1. materialize deferred dynamic module descriptors;
2. let the selected adapter contribute explicit compilation extensions;
3. validate and build the module/provider resolution graph;
4. create the adapter binder and validate its driver plans;
5. return an unstarted `NestApplication`.

It MUST NOT open provider resources, call lifecycle hooks, or accept HTTP work.

### 4.2 ASGI adapter

External ASGI servers need a synchronous importable ASGI callable. Nestpy
provides an adapter:

```python
from nestpy.starlette import asgi

application = asgi(create_application)
```

`asgi()` requires the factory result to use `StarletteAdapter` and returns a
normal ASGI callable. During the server lifespan startup it
awaits `create_application()` exactly once, then invokes
`application.start()`. The wrapper delegates HTTP to the adapter-owned Starlette
application only after successful startup. HTTP before lifespan readiness
returns 503 Problem Details.

During lifespan shutdown the wrapper invokes `application.shutdown()` exactly
once. Concurrent lifespan startup/shutdown events are serialized. Re-entering
the same application instance after shutdown is invalid; a server restart must
call the exported factory again and receive a new instance.

Examples:

```text
uvicorn myapp:application
nestpy run myapp:create_application
```

The CLI accepts `nestpy run module:factory` and non-secret
`--set namespace.path=value` arguments. It wraps the factory with a
`BootstrapContext`; the ASGI lifespan wrapper awaits that contextual factory in
the server event loop. The CLI MUST NOT await the factory in one event loop and
then hand the application to another. It is not a second application
composition API.

## 5. Modules

### 5.1 Static modules

```python
from nestpy import module


@module(
    imports=[SettingsModule.for_root(...)],
    providers=[UserRepositoryProvider, UserServiceProvider],
    controllers=[UsersController],
    exports=[UserService],
)
class UsersModule:
    pass
```

Module metadata has these fields:

- `imports`: module classes or deferred dynamic descriptors;
- `providers`: module-owned provider declarations;
- `controllers`: module-owned controller classes;
- `exports`: public provider tokens;
- `global_`: explicit `False` by default.

A static module class has one identity per application graph. Importing the
same static module class from several places reuses that single module node.
A static module node and a dynamic descriptor for the same module class cannot
coexist: importing both is a bootstrap error. A module must be imported either
as its static form or through one or more explicitly keyed dynamic descriptors.

### 5.2 Dynamic modules

Dynamic module methods return immutable deferred descriptors, not a materialized
module spec and not opened resources:

```python
class SettingsModule:
    @classmethod
    def for_root(
        cls,
        options: SettingsOptions,
        *,
        key: str = "default",
        global_: bool = False,
    ) -> DeferredModule:
        return DeferredModule(
            module=cls,
            key=key,
            factory=lambda: cls._materialize(options, global_=global_),
        )
```

The deferred factory runs during `NestApplication.create()`. It MAY be async
and returns a normalized `ModuleSpec`.

Dynamic identity is `(module class, key)`. The same `DeferredModule` object may
be imported repeatedly and is materialized once. A different descriptor object
with the same identity is always a bootstrap error, without materializing or
comparing both specs. Different keys create distinct configured module nodes;
there is no automatic configuration hashing or arbitrary `ModuleSpec.__eq__`.

A dynamic descriptor may not use a key named `"static"`; that reserved key
prevents an accidental collision with the static module identity domain.

### 5.3 Visibility and resolution

Provider lookup in module `M` follows exactly this order:

1. provider declared locally by `M`;
2. an explicitly exported provider of a direct import of `M`;
3. an explicitly exported provider of an opt-in global module.

At every level, more than one matching token is an ambiguity error. There is no
registration-order fallback.

Exports are not automatically transitive. If module `A` imports `B`, and `B`
imports `C`, `A` sees only tokens that `B` explicitly exports. A module may
re-export a token that it can resolve through its own direct imports.

Global modules participate only at step 3 and still export tokens explicitly.
They never override local or direct-import providers.

### 5.4 Bootstrap graph errors

Compilation MUST fail before ASGI startup for:

- cyclic module imports;
- different dynamic descriptor objects with the same identity;
- unresolved provider dependencies;
- provider dependency cycles, including alias cycles;
- ambiguous direct-import or global token resolution;
- invalid exports;
- invalid scope paths;
- exact duplicate normalized HTTP method/path definitions;
- invalid controller, provider factory, or handler signatures.

## 6. Native DI Container

### 6.1 Decision

Nestpy uses a native DI container. `dependency_injector` is not the primary
runtime because Nestpy must own module visibility, async resource ownership,
scope diagnostics, and minimal-dependency semantics.

An optional external-container bridge may be designed later. It cannot change
the semantics in this document.

### 6.2 Tokens and providers

A token is either a class or a string constant:

```python
USER_REPOSITORY = "users.repository"
```

Provider declarations are always explicit:

```python
ValueProvider("settings", settings)
ClassProvider(UserService, UserService, scope="singleton")
FactoryProvider(USER_REPOSITORY, create_repository, scope="singleton")
AliasProvider(UserReader, USER_REPOSITORY)
```

Provider forms:

- `ValueProvider`: returns an explicit value;
- `ClassProvider`: constructs an explicit class;
- `FactoryProvider`: invokes an explicit sync or async factory;
- `AliasProvider`: resolves an existing token without creating another object.

Alias providers have the effective scope and identity of their target. They do
not own cleanup independently.

### 6.3 Constructor and factory injection

Only explicit class/factory providers receive annotation-based dependency
resolution:

```python
class UserService:
    def __init__(
        self,
        repository: Annotated[UserRepository, Inject(USER_REPOSITORY)],
        settings: Settings,
    ) -> None:
        ...
```

Rules:

1. A class annotation resolves the class token.
2. `Annotated[T, Inject(token)]` overrides the token.
3. Every required constructor/factory parameter needs an annotation or `Inject`
   marker.
4. Default values are application defaults, not DI tokens.
5. Unregistered classes are never automatically registered.
6. Annotation resolution follows the owning module's visibility rules.

### 6.4 Scopes and ownership

Scopes:

- `singleton`: one eagerly-created instance per application;
- `request`: one instance per accepted HTTP request or explicit work scope;
- `transient`: a new instance per resolution.

Singleton providers may inject the reserved `WorkScopeFactory` intrinsic. The
factory is bound to the provider's exact compiled `ModuleId` and opens a fresh,
application-tracked work scope on each call. Work scopes use normal module
visibility, cache request-scoped providers once per invocation, own transient
resources, and cannot be declared or overridden as a user provider.
`WorkScopeFactory.run()` executes an operation in a fresh
`contextvars.Context`, so background work does not inherit HTTP request,
logging, or other ambient execution context. Direct `open()` controls DI
lifetime only and does not clear context variables.

All singleton providers, including controllers, are created during application
startup. This makes hooks, resource acquisition, and startup failures
deterministic.

The container validates the complete transitive dependency graph. A singleton
MUST NOT reach a request-scoped provider through any path, including through
transient providers. Request and transient providers may depend on singleton
providers. Transient resources are owned by the scope resolving them:

- a transient resolved while constructing a singleton belongs to application
  cleanup;
- a transient resolved in a request belongs to that request cleanup;
- a transient resolved by another transient inherits its current owner scope.

### 6.5 Resource protocol

Provider values can own resources through the normal Python context-manager
protocol:

- `__enter__` / `__exit__`;
- `__aenter__` / `__aexit__`.

`ClassProvider` and `FactoryProvider` resources are managed by default.
`ValueProvider` is managed only with explicit `manage=True`; otherwise a value
is application-owned. `AliasProvider` never manages the target resource.

When a managed provider returns a context manager, the container enters it
before exposing the dependency to a consumer. Consumers receive the value
returned by `__enter__` or `__aenter__`, never the unentered manager object.
The entered manager is retained as the scope's cleanup handle.

Async context managers execute in the application event loop. Sync
`__enter__`/`__exit__` calls execute in a framework-owned executor and MUST NOT
block the event loop. Cancelling the awaitable does not terminate its worker
thread: after the shutdown deadline Nestpy stops waiting, observes the future,
and logs the lingering provider/module/scope. Thread affinity is not guaranteed;
thread-affine resources require an application-provided async wrapper.

On partial acquisition failure, already-entered resources of the current scope
close immediately in reverse order. The original acquisition error is
preserved; cleanup errors are attached/logged as secondary failures.

### 6.6 Reflection and compiled-provider discovery

Nestpy exposes typed, Python-native metadata without depending on JavaScript's
`reflect-metadata` model. Metadata decorators attach immutable values directly
to classes or functions. `Reflector` reads metadata from a class, function, or
instance and exposes separate direct-only and inherited lookup operations.
Existing framework metadata whose contract is direct-only remains direct-only.

`ModulesContainer` is one application-owned, read-only view of the complete
compiled module graph. `DiscoveryService` can enumerate provider and controller
descriptors from that view in deterministic compiled order. These services are
reserved framework dependencies available through constructor injection; they
never register providers or scan importable Python packages.

Discovery is privileged introspection and may include private providers from
every compiled module, matching NestJS discovery semantics. Every descriptor
retains its exact `ModuleId`, provider token, canonical `ProviderRef`, scope,
declaration, implementation class when statically knowable, and resolved
singleton instance plus an explicit created-state when available. A created
provider may validly hold `None`. The public view is immutable and does not
expose mutable caches, resource stacks, or container mutation APIs.

Global discovery MUST NOT imply unqualified global resolution. Integrations
execute discovered providers through the descriptor's module-qualified
identity. Two providers with the same token in different static or dynamic
modules remain distinct and deterministic. Aliases canonicalize to one provider
for discovery unless an integration explicitly requests alias declarations.

`WorkScopeFactory.run_in(module_id, operation)` is the privileged scoped
execution primitive for a discovered provider. It opens one application-tracked
work scope owned by the exact target module and preserves the same context
isolation, admission, cancellation, and cleanup guarantees as `run()`.

## 7. Lifecycle and Shutdown

Application behavior is configured explicitly:

```python
@dataclass(frozen=True, slots=True)
class ApplicationOptions:
    shutdown_timeout: float = 30.0
    cancellation_grace: float = 1.0
    cleanup_reserve: float = 5.0


@dataclass(frozen=True, slots=True)
class PipelineOptions:
    middleware: tuple[Token, ...] = ()
    guards: tuple[Token | Guard, ...] = ()
    pipes: tuple[Token | Pipe, ...] = ()
    interceptors: tuple[Token | Interceptor, ...] = ()
    filters: tuple[Token | ExceptionFilter, ...] = ()


@dataclass(frozen=True, slots=True)
class StarletteOptions:
    body_size_limit: int = 1024 * 1024
```

`ApplicationOptions` and `PipelineOptions` belong to the driver-neutral
application facade. `StarletteOptions` contains transport settings only, belongs
to `nestpy.starlette`, and is passed to `StarletteAdapter`.

An application factory MAY append global enhancer bindings with
`NestApplication.use_global_guard()`,
`use_global_pipe()`, `use_global_interceptor()`, and `use_global_filter()` while
the application remains compiled but unstarted. These methods preserve
registration order and return the application for chaining. Preconstructed
instances are externally owned. Provider tokens and registered class tokens are
accepted when visible from the compiled root module and retain DI scope and
lifecycle ownership. An unregistered implementation class remains a compile-time
`PipelineOptions` registration because implicit provider creation requires graph
compilation. The application passes each updated immutable configuration
snapshot through `ApplicationAdapter.configure_pipeline()` before binding.

Global pipeline tokens are qualified once against the compiled root-module
visibility and stored as module-qualified `ProviderRef` values before binding.
Initial `PipelineOptions` are qualified during application creation; fluent
registrations are revalidated and qualified when their immutable configuration
snapshot reaches the adapter. Controller and route pipeline tokens resolve from
their owning module. Runtime dispatch never re-resolves an unqualified global
token from a route module.

Options require `cancellation_grace + cleanup_reserve <= shutdown_timeout`.
Request draining stops at
`deadline - cancellation_grace - cleanup_reserve`, reserving bounded time for
cancellation observation, hooks, and resource cleanup.

`nestpy.core` owns an internal `ApplicationKernel` with the state machine,
container, lifecycle, options, and an exact-once async `DriverBinder` protocol.
`nestpy.application` owns the public driver-neutral `NestApplication` and
`ApplicationAdapter`, `ApplicationBinder`, and `ApplicationRuntime` protocols.
Concrete adapters explicitly implement `ApplicationAdapter`; its pipeline
configuration hook applies pre-start global binding snapshots without
moving pipeline ordering or resolution into the transport.
The immutable compiled graph identities used by adapter authors are public core
contracts. N2 implements the kernel with a no-op adapter for non-HTTP
applications and tests. The application layer compiles global/controller/route
pipeline providers independently of a transport. N4 introduces `nestpy.http`
for HTTP route plans, execution contexts, errors, validation, and pipeline
orchestration. `StarletteAdapter` supplies native route registration, request
binding, response rendering, ASGI lifecycle, and the concrete binder. Core,
application, and HTTP layers never import the Starlette adapter.

`DriverBinder.bind()` MUST be failure-atomic where possible. The lifecycle marks
binding attempted before awaiting it and invokes idempotent `close()` after any
successful or failed attempt. If later bootstrap hooks fail, binder close occurs
after reverse application-shutdown hooks and before module-destroy hooks. Normal
shutdown uses the same reverse ownership order and remaining cleanup reserve.

Module classes are instantiated with no arguments during startup. Module
instances exist only for lifecycle hooks and never receive constructor DI.

Lifecycle participants are module instances and all eagerly-created singleton
providers/controllers. The supported async hook names are:

- `on_module_init()`;
- `on_application_bootstrap()`;
- `on_application_quiesce(context)`;
- `on_application_shutdown()`;
- `on_module_destroy()`.

`on_application_quiesce()` receives a `ShutdownContext` exposing the remaining
graceful drain budget. It MUST be async, accept exactly one context argument,
stop new subsystem intake, drain queued work, and cooperate with cancellation
at the cutoff. Other hooks remain async no-argument bound methods.

Startup receives an already compiled graph. Startup order is deterministic:

1. create singleton providers in topological dependency order; provider
   declaration order is only the tie-breaker for independent providers;
2. enter singleton resources before exposing them to dependent providers;
3. call `on_module_init()` on modules, then singleton providers/controllers,
   in the same dependency order;
4. bind the already-compiled route definitions once to the started singleton
   controller instances and construct the Starlette route table;
5. open work-scope admission;
6. call `on_application_bootstrap()` in the same order;
7. admit normal driver/HTTP requests.

Independent modules are ordered by their root/import declaration order. Within
one module, providers precede controllers and preserve declaration order.

If startup fails, Nestpy rolls back every entered resource and successful hook
participant in reverse order. `on_application_shutdown()` is called only for
participants that reached bootstrap; `on_module_destroy()` is called for every
participant that reached module initialization.

Shutdown uses a single deadline from application configuration:

1. close the normal request-admission gate;
2. call `on_application_quiesce()` in reverse bootstrap order while work scopes
   remain admissible;
3. close work-scope admission;
4. wait for active request/work tasks only until the reserved drain cutoff;
5. cancel remaining scope-owner tasks;
6. wait one configured cancellation grace interval capped by the remaining
   shared shutdown deadline;
7. run shutdown hooks and close resources within remaining time;
8. observe and log every task/resource still open when the deadline expires;
9. return from public shutdown without starting unbounded background cleanup.

The first shutdown failure is preserved while remaining cleanup proceeds. A
resource that ignores cancellation may remain open; Nestpy logs its token,
module, scope, and state. It does not promise impossible cleanup after the
deadline.

Normal shutdown order is the reverse of startup ownership:

1. quiesce started singleton controllers/providers and modules in reverse
   dependency order while work scopes remain available;
2. drain and close request/work scopes;
3. call `on_application_shutdown()` on started singleton controllers/providers,
   then modules, in reverse dependency order;
4. close the bound driver exactly once;
5. call `on_module_destroy()` on module-initialized participants in the same
   reverse order;
6. close scoped resources first, then singleton resources in strict LIFO
   acquisition order.

Concurrent callers join one shielded shutdown operation. Cancelling a caller
does not cancel cleanup. Provider construction remains authoritative in the
scope's in-flight registry when one resolver waiter is cancelled, and scope
cleanup itself runs exactly once in a shielded task.

## 8. Driver-Neutral Execution Context

`nestpy.core` defines a driver-neutral `ExecutionContext` protocol for guards,
pipes, interceptors, and filters. It exposes only:

- application/module/route identifiers;
- request ID;
- scoped DI resolver;
- metadata mapping;
- execution kind such as `"http"`.

The resolver exposed by an execution context is backed by an invalidatable
`ScopeLease`. Every resolution checks that the lease remains open. Request
completion invalidates the lease exactly once and resets framework context
variables; subsequent use raises `ScopeClosedError`. Detached tasks cannot
silently resolve new request-scoped providers after request cleanup.

It has no Starlette types or driver-specific methods. `nestpy.http.HttpContext`
is the portable HTTP implementation and carries an opaque native request plus
request-scope and route metadata. `nestpy.starlette.RequestContext` subclasses
it and exposes Starlette-specific method/path/header/query/cookie access. Route
handlers should annotate `HttpContext` unless they intentionally require the
native Starlette request escape hatch.

Settings validation uses a core `Codec`/`SettingsDecoder` protocol, not HTTP
`Pipe`.

## 9. Nestpy HTTP and Starlette Driver

### 9.1 Controllers and routes

```python
from nestpy.http import HttpContext


@controller("/users")
class UsersController:
    def __init__(self, service: UserService) -> None:
        self._service = service

    @post("/")
    @status(201)
    async def create(
        self,
        body: Annotated[CreateUser, Body()],
        context: Annotated[HttpContext, Context()],
    ) -> User:
        return await self._service.create(body, context.request_id)
```

Controllers are mandatory eager singleton class providers in v1. Request and
transient controller scopes are bootstrap errors. Route methods receive request
data through binding; they must not retain `HttpContext` beyond the request
lifetime.

### 9.2 Route compilation

Nestpy does not implement a router. It joins controller prefixes and method
paths, validates decorator metadata, rejects only exact duplicate normalized
method/path identities, and creates Starlette `Route` objects in declaration
order. Overlap precedence, converters, trailing-slash redirects, implicit HEAD,
OPTIONS, and Allow behavior follow the pinned Starlette driver version.

Exact duplicate normalization adds one leading slash and collapses only the
single join boundary between controller prefix and route path. It preserves the
trailing slash, parameter names, converter text, and segment spelling. Method
names are uppercased; GET reserves its implicit HEAD method for duplicate
checks. Thus `/x` and `/x/`, and `/{id}` and `/{name}`, are not exact duplicates
and retain Starlette ordering behavior.

Unmatched `404` and `405` responses are adapted into Problem Details and pass
through global filters using a partial HTTP execution context with no route or
controller identity. Controller and route filters become available only after a
successful route match.

### 9.3 Parameter binding

Except for `self`, every controller parameter MUST have exactly one binding
marker or `Inject` marker:

- `Annotated[T, Body()]`;
- `Annotated[T, Path("source_name")]`;
- `Annotated[T, Query("source_name")]`;
- `Annotated[T, Header("source-name")]`;
- `Annotated[T, Cookie("source_name")]`;
- `Annotated[HttpContext, Context()]`;
- `Annotated[T, Inject(token)]`.

There is no parameter-name inference. Non-body HTTP markers require an explicit
source name. Missing required values, duplicate body markers, unknown markers,
and unsupported annotations are bootstrap or request validation errors as
appropriate. An adapter validates that its concrete native context subtype can
satisfy each declared `HttpContext` annotation. An annotated default value makes
an input optional; otherwise it is required.

The v1 body format is JSON. Binding extracts raw JSON-compatible values and raw
path/query/header/cookie text without converting to the declared target type.
The driver requires JSON media type for `Body()` and enforces the configured
body-size limit while receiving. One handler has at most one body marker.
Repeated query/header values remain a raw sequence for a later pipe.

### 9.4 Response contract

Nestpy JSON-encodes primitives, mappings, sequences, and msgspec/dataclass
structs. An explicit Starlette `Response` is passed through unchanged.

For any explicit response, Nestpy retains the request scope until awaiting the
response ASGI call has completed, including Starlette background tasks. Route
status/header decorators apply only to Nestpy-encoded values; an explicit
response owns its own status and headers.

Streaming, file, and background responses are therefore supported only through
the Starlette escape hatch. Their portability to future drivers is not a v1
guarantee.

## 10. Pipeline Contract

Pipeline registration, qualification, DI resolution, and execution are Nestpy
framework responsibilities. They MUST NOT be implemented by a concrete HTTP
transport adapter. HTTP adapters provide native argument extraction, explicit
response recognition/rendering, disconnect classification, and route
registration callbacks to the framework-owned executor.

After route matching and request-scope creation, the runtime executes:

```text
filter boundary(
  global middleware -> controller middleware -> route middleware ->
  global guards -> controller guards -> route guards ->
  bind arguments ->
  global pipes -> controller pipes -> route pipes ->
  global interceptors -> controller interceptors -> route interceptors ->
  handler -> response encoding
)
```

Interceptors unwind in reverse order around handler execution. Filters catch
every `Exception` after route match, including middleware, guards, binding,
pipes, interceptors, handlers, and encoding. They MUST NOT catch or convert
`asyncio.CancelledError`, `KeyboardInterrupt`, `SystemExit`, or other
`BaseException` values. If no filter handles an error, the default Problem
Details renderer does.

Filters are tried route first, then controller, then global. A filter either
returns a response or re-raises; re-raising selects the next filter. Errors
raised by a filter itself continue to the next eligible filter, then the
default renderer.

Middleware registrations are provider tokens. Guard, pipe, interceptor, and
filter registrations accept provider tokens, implementation classes, or
preconstructed protocol instances. An implementation class is implicitly added
as a class provider in the declaring module only when no explicit provider for
that token is visible; it therefore uses normal constructor injection, scope,
and lifecycle behavior. A preconstructed instance is shared, externally owned,
and does not receive injection, scope conversion, or lifecycle management.

Provider-backed registrations resolve from the current request scope, so
request-scoped guards/pipes/interceptors/filters are valid. Singular
`use_guard`, `use_pipe`, `use_interceptor`, and `use_filter` decorators are
convenience forms of their ordered plural counterparts.

Ordering is deterministic:

- global registrations follow application configuration order;
- controller registrations follow the tuple order in one decorator;
- route registrations follow the tuple order in one decorator;
- declaring the same pipeline-kind decorator twice on one controller/route is
  a bootstrap error; use one decorator with an ordered tuple instead.

Guard protocol:

```python
class Guard(Protocol):
    async def can_activate(self, context: ExecutionContext) -> bool: ...
```

`False` maps to a standard forbidden HTTP exception. Nestpy supplies no auth
or security policy beyond this extension point.

Middleware protocol:

```python
type Next = Callable[[], Awaitable[PipelineResult]]


class Middleware(Protocol):
    async def handle(
        self,
        context: ExecutionContext,
        next: Next,
    ) -> PipelineResult: ...
```

Each `Next` is one-shot. A second invocation raises `PipelineStateError`; this
prevents duplicate downstream execution and resource acquisition.

Pipe protocol:

```python
class Pipe(Protocol):
    async def transform(self, value: object, metadata: ArgumentMetadata) -> object: ...
```

`ArgumentMetadata` contains the handler parameter name, binding kind, explicit
source name, declared annotation, route identifier, and module identifier.
Pipes run one argument at a time in handler-parameter order. For each argument,
global pipes run first, then controller pipes, then route pipes.

```python
class Interceptor(Protocol):
    async def intercept(
        self,
        context: ExecutionContext,
        next: Next,
    ) -> PipelineResult: ...


class ExceptionFilter(Protocol):
    async def catch(
        self,
        error: Exception,
        context: ExecutionContext,
    ) -> PipelineResult: ...
```

`PipelineResult` is a driver-neutral core value: either an application value
awaiting driver encoding or an explicit driver response held as opaque data.
The Starlette driver maps it to ASGI output. A filter can return a replacement
`PipelineResult` only before ASGI response transmission starts. Failures during
or after ASGI response transmission are logged with request ID and cannot be
re-rendered by filters.

## 11. Errors and Validation

### 11.1 Problem Details

Nestpy `HttpException` defaults to RFC 9457 `application/problem+json`:

```json
{
  "type": "about:blank",
  "title": "Bad Request",
  "status": 400,
  "detail": "Invalid request body",
  "instance": "/users"
}
```

Validation failures add a structured `errors` extension. Unexpected exceptions
log request ID and return 500 without source stack traces by default.

### 11.2 Msgspec validation

`msgspec` is the required v1 typed decoder/encoder for settings and the default
validation integration. Nestpy does not implement a separate permissive
dataclass decoder.

HTTP binding itself remains raw. An opt-in `MsgspecValidationPipe`, registered
globally, on a controller, or on a route, converts HTTP-bound arguments to their
declared target annotations and produces structured 400 Problem Details on
decode failure. Pipes apply only to Body/Path/Query/Header/Cookie arguments;
`Context()` and `Inject()` arguments never pass through pipes. Future validators
integrate through the same pipe/codec contract.

## 12. SettingsModule

`SettingsModule` is a dynamic module and may be global only through explicit
`global_=True`:

```python
SettingsModule.for_root(
    SettingsOptions(
        model=AppSettings,
        base_dir=Path(__file__).parent,
        files=["config/base.toml", "config/prod.yaml"],
        dotenv_files=[".env"],
    ),
    global_=True,
)
```

Supported v1 sources, from lowest to highest precedence:

```text
msgspec/dataclass defaults
-> explicit TOML/JSON/YAML files
-> explicit dotenv files
-> process environment
-> CLI overrides supplied by nestpy run
```

Rules:

- files are always explicitly listed; Nestpy never scans a working directory;
- relative paths resolve from explicit `base_dir`;
- later files merge recursively over earlier mappings; scalar and sequence
  values replace earlier values;
- TOML uses `tomllib`, JSON uses the standard library, YAML uses only
  `yaml.safe_load` and requires the `settings-yaml` extra;
- dotenv supports `KEY=VALUE`, comments, and basic single/double quoting; it
  does not support interpolation or multiline values;
- nested environment names use double underscores, for example
  `DATABASE__HOST` for `database.host`;
- CLI overrides use repeated `--set namespace.path=value` flags and are exposed
  to deferred settings descriptors through `BootstrapContext`; any override
  targeting a `Secret[T]` path is rejected, so secrets come only from explicit
  files, dotenv, or environment;
- external ASGI hosting has no implicit CLI source; callers pass settings
  options or equivalent overrides through the exported factory;
- `Secret[T]` annotations mark fields for redaction in logs/errors;
- settings decode/validation occurs during dynamic module materialization;
- settings resolution errors prevent ASGI startup.

## 13. Logging and Request IDs

Nestpy exposes an injectable `Logger` token/protocol with structured fields.
The default logger uses Python logging and includes module, provider, route,
scope, and request ID where available.

The Starlette driver uses `X-Request-ID`:

- accept inbound IDs matching `[A-Za-z0-9._-]{1,128}`;
- reject unsafe/oversized IDs as correlation values, generate UUIDv7 instead,
  and log a warning without echoing the unsafe input;
- generate UUIDv7 when no header exists;
- expose the ID in `RequestContext` and response `X-Request-ID`;
- reject duplicate inbound `X-Request-ID` fields as invalid correlation input;
- overwrite a conflicting `X-Request-ID` on an explicit Starlette response with
  the framework-owned request ID;
- treat the ID as observability metadata only, never as an authentication or
  authorization signal.

## 14. Testing

```python
testing = TestingModule.create(AppModule)
testing.override_provider(USER_REPOSITORY, module=UsersModule).use_value(
    fake_repository
)
application = await testing.compile()
```

`TestingModule.create()` records provider and deferred-module overrides without
materializing the graph. `compile()` applies module overrides before dynamic
materialization, validates module/route/provider shape, applies eligible public
provider overrides, validates dependency resolution/scopes, starts the
application, and returns a ready testing application.

Overrides are limited to exported tokens of the target module or global tokens.
Private same-token providers cannot be overridden from outside their module.
An override identifies its target module explicitly. Dynamic modules use their
identity tuple:

```python
testing.override_provider(USER_REPOSITORY, module=UsersModule)
testing.override_provider(SETTINGS, module=(SettingsModule, "default"))
```

The testing application exposes a documented module-bound resolver facade and
ASGI app, not mutable container caches/resource stacks. It has an async
`close()` method that executes the same bounded shutdown behavior as a
production application.

## 15. Optional CQRS Bridge

The implemented integration is a separate package:

```text
nestpy-cqrs -> nestpy, cqrs-core
```

It provides CQRS buses as Nestpy providers, discovers decorated provider
classes from the compiled application graph, and maps each handler invocation
to an isolated module-qualified work scope. Background event handling never
retains HTTP request-scoped dependencies. Neither `nestpy.core` nor
`nestpy.starlette` imports `cqrs-core`.

The bridge architecture and executable phases are maintained separately in
[`NESTPY_CQRS_ARCHITECTURE.md`](NESTPY_CQRS_ARCHITECTURE.md) and
[`spec/nestpy-cqrs/README.md`](spec/nestpy-cqrs/README.md).

## 16. Implementation Plan

### N0: Workspace and contracts

Detailed specification: [`spec/nestpy/phase-n0-workspace-and-contracts.md`](spec/nestpy/phase-n0-workspace-and-contracts.md)

### N1: Module compiler and visibility

Detailed specification: [`spec/nestpy/phase-n1-module-compiler.md`](spec/nestpy/phase-n1-module-compiler.md)

### N2: DI runtime and lifecycle

Detailed specification: [`spec/nestpy/phase-n2-di-runtime-and-lifecycle.md`](spec/nestpy/phase-n2-di-runtime-and-lifecycle.md)

### N3: Settings, logging, and testing

Detailed specification: [`spec/nestpy/phase-n3-settings-logging-testing.md`](spec/nestpy/phase-n3-settings-logging-testing.md)

### N4: Starlette application and controllers

Detailed specification: [`spec/nestpy/phase-n4-starlette-http.md`](spec/nestpy/phase-n4-starlette-http.md)

### N5: HTTP pipeline and errors

Detailed specification: [`spec/nestpy/phase-n5-pipeline-and-errors.md`](spec/nestpy/phase-n5-pipeline-and-errors.md)

### N6: CLI and hardening

Detailed specification: [`spec/nestpy/phase-n6-cli-and-hardening.md`](spec/nestpy/phase-n6-cli-and-hardening.md)

### N7: Reflection and discovery

Detailed specification: [`spec/nestpy/phase-n7-reflection-and-discovery.md`](spec/nestpy/phase-n7-reflection-and-discovery.md)

The optional `nestpy-cqrs` bridge consumes N7 through its separate C2 phase.

## 17. Exit Criteria

Nestpy v1 is complete when a multi-module Starlette app can:

1. bootstrap from an async exported factory exactly once per ASGI lifespan;
2. resolve explicit providers through module visibility and scopes;
3. reject scope, dependency, module, and route conflicts before serving;
4. close sync/async resources correctly on startup failure, shutdown timeout,
   and cancellation;
5. execute controller routes with marker-only typed binding;
6. run the documented pipeline order and render Problem Details;
7. load and validate settings from all defined sources with secret redaction;
8. create testing applications with public provider overrides;
9. expose request IDs and structured framework logging;
10. keep `nestpy.core` independent from Starlette and CQRS imports.
