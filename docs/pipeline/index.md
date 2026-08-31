# Request Pipeline

ToriPy owns one deterministic HTTP request pipeline across all transports. The
Starlette adapter supplies routing, raw argument extraction, native response
recognition, and abort classification; it does not redefine enhancer ordering
or provider resolution.

## Pipeline Stages

After ToriPy opens a request scope and Starlette matches a route, execution is:

```text
error/filter boundary(
  global middleware -> controller middleware -> route middleware ->
  global guards -> controller guards -> route guards ->
  enforce @no_body and bind all raw arguments ->
  pipes per argument: global -> controller -> route ->
  global interceptors -> controller interceptors -> route interceptors ->
  handler -> interceptor unwind -> middleware unwind ->
  body-stream completion check -> response encoding
)
```

Middleware and interceptors are nested around their downstream stages. Their
entry order is global, controller, route; after `next()` their exit order is
route, controller, global. Filters are not an ordinary forward stage: they are
consulted only after an eligible exception escapes, in route, controller,
global order.

See [Ordering and Cancellation](ordering-and-cancellation.md) for the exact
success, error, short-circuit, disconnect, and response-transmission paths.

## Pipeline Contracts

Public structural protocols are available from `tori_py`:

| Component | Method | Purpose |
| --- | --- | --- |
| `Middleware` | `handle(context, next)` | Wrap all downstream HTTP dispatch or short-circuit it |
| `Guard` | `can_activate(context)` | Permit or deny dispatch |
| `Pipe` | `transform(value, metadata)` | Transform one extracted argument |
| `Interceptor` | `intercept(context, next)` | Wrap the handler result or short-circuit the handler |
| `ExceptionFilter` | `catch(error, context)` | Map one eligible exception to a `PipelineResult` |

`ExecutionContext` is driver-neutral. `PipelineResult` distinguishes an
application value from an explicit response. `ArgumentMetadata` describes the
parameter currently passing through a pipe.

## Registration Levels

Pipeline components may be global, controller-level, or route-level:

```python
from tori_py import (
    PipelineOptions,
    controller,
    get,
    use_guard,
    use_interceptor,
    use_middleware,
    use_pipe,
)


@controller("/reports")
@use_middleware("request-log")
@use_guard("authenticated")
class ReportsController:
    @get("")
    @use_pipe("report-query")
    @use_interceptor("response-envelope")
    async def list(self) -> list[object]:
        return []


pipeline = PipelineOptions(
    middleware=("global-request-log",),
    guards=("service-ready",),
    pipes=("validation",),
    interceptors=("metrics",),
    filters=("problem-mapping",),
)
```

Pass `pipeline` to `NestApplication.create(...)`. Registrations preserve tuple
order at each level.

The aliases `middleware`, `guards`, `pipes`, `interceptors`, and `filters` are
equivalent to their plural `use_*` decorators. Singular `use_guard`,
`use_pipe`, `use_interceptor`, and `use_filter` are convenience forms.
Middleware has only the token-based `use_middleware` form.

## Provider Forms and Ownership

Middleware registrations are provider tokens only. The class or string token
must be visible from the registration's owning module, and middleware classes
must have an explicit provider declaration.

Guards, pipes, interceptors, and filters accept:

- a visible string or class provider token;
- an implementation class;
- a preconstructed protocol instance.

An unregistered implementation class present during graph compilation becomes
an implicit class provider in the declaring module. It receives normal
constructor injection, scope, lifecycle, and cleanup. An explicit visible
provider for that class token takes precedence.

A preconstructed instance is shared and externally owned. ToriPy does not
inject into it, change its scope, call lifecycle hooks, or clean it up. Such an
instance must be safe for concurrent requests.

Provider-backed components may be singleton, request-scoped, or transient.
They resolve from the current request scope and preserve normal resource
ownership.

## Module Qualification

Global provider tokens are resolved once from root-module visibility and stored
as qualified provider references. A same-named token in a route's feature
module does not override the global component.

Controller and route tokens resolve from the controller's owning module. They
may use local providers, direct imported exports, or visible global exports
according to normal module visibility.

Unresolved or invisible registrations fail before startup. This qualification
prevents runtime behavior from depending on whichever module happened to own a
matched route.

## Fluent Global Registration

After `NestApplication.create()` and before startup, an application factory may
append global guards, pipes, interceptors, and filters:

```python
app.use_global_guard("authenticated")
app.use_global_pipe("validation")
app.use_global_interceptor(MetricsInterceptor())
app.use_global_filter(DomainFilter())
```

There is no fluent global middleware method; configure middleware in the
compile-time `PipelineOptions`.

Fluent registrations may use preconstructed instances or provider tokens
already visible in the compiled root graph. They cannot create a new implicit
provider after compilation. Put an unregistered enhancer class in the initial
`PipelineOptions` if compilation must create its fallback provider. Calling a
fluent method after startup raises `ApplicationStateError`.

## Errors and Short Circuits

- Middleware may return without calling `next()`, skipping guards, binding,
  pipes, interceptors, and the handler.
- A guard returning `False` raises standard 403 `HttpException`.
- An interceptor may return without calling `next()`, skipping the handler, but
  argument binding and pipes have already run.
- Middleware and interceptor `next` callbacks are one-shot. Calling one twice
  raises `PipelineStateError`.
- Any eligible pre-start `Exception` proceeds through route, controller, then
  global filters, followed by the default Problem Details renderer.
- Cancellation, process-control exceptions, and client-disconnect aborts bypass
  filters.

## Guides

- [Middleware and Guards](middleware-and-guards.md)
- [Pipes and Validation](pipes-and-validation.md)
- [Interceptors and Filters](interceptors-and-filters.md)
- [Ordering and Cancellation](ordering-and-cancellation.md)
- [HTTP Request Binding](../http/binding.md)
- [Responses and Errors](../http/responses-and-errors.md)

## Testing and Production Advice

- Test observable order with event recording rather than relying on decorator
  appearance alone.
- Use request-scoped providers when a component owns per-request mutable state.
- Keep preconstructed global instances stateless or concurrency-safe.
- Let unrecognized exceptions and cancellation propagate; do not write a filter
  that turns every failure into success.
- Keep middleware broad and cheap. Put parameter-specific work in pipes and
  handler-result work in interceptors.
- Use one decorator per pipeline kind on a target, with all desired bindings in
  one ordered tuple.

## Related API

`PipelineOptions`, `Middleware`, `Guard`, `Pipe`, `Interceptor`,
`ExceptionFilter`, `ExecutionContext`, `ArgumentMetadata`, `PipelineResult`,
`PipelineStateError`, and all `use_*` pipeline decorators.
