# Middleware and Guards

Middleware wraps the complete downstream route dispatch. Guards make a
sequential allow/deny decision after middleware enters and before request
arguments are bound.

## Middleware

A middleware provider implements `handle(context, next)` and returns a
`PipelineResult`:

```python
from time import monotonic

from tori_py import ExecutionContext, Middleware, PipelineResult


class RequestTimingMiddleware:
    async def handle(
        self,
        context: ExecutionContext,
        next,
    ) -> PipelineResult:
        started = monotonic()
        try:
            return await next()
        finally:
            elapsed = monotonic() - started
            # Send elapsed to an injected metrics provider in production.
            del context, elapsed
```

Middleware registrations are provider tokens. Declare the provider explicitly
and reference its token:

```python
from tori_py import ClassProvider, controller, get, module, use_middleware


@controller("/reports")
@use_middleware(RequestTimingMiddleware)
class ReportsController:
    @get("")
    async def list(self) -> list[object]:
        return []


@module(
    providers=[ClassProvider(RequestTimingMiddleware)],
    controllers=[ReportsController],
)
class ReportsModule:
    pass
```

Unlike guards, pipes, interceptors, and filters, middleware does not accept a
direct instance and does not receive an implicit class-provider fallback. A
class is valid syntax because it is a provider token, but that token must be
declared and visible.

Configure global middleware only through compile-time `PipelineOptions`:

```python
from tori_py import PipelineOptions

pipeline = PipelineOptions(middleware=(RequestTimingMiddleware,))
```

The root module must be able to resolve that token.

## Middleware Ordering

Middleware enters in this order:

1. Global registrations.
2. Controller registrations.
3. Route registrations.

Before the first `handle()` call, ToriPy resolves every global, controller, and
route middleware provider in that order. It then invokes middleware in the same
order and unwinds in reverse after `next()` returns. For registrations `G`, `C`,
and `R`, observable method order is:

```text
G in -> C in -> R in -> downstream -> R out -> C out -> G out
```

If downstream raises, code after `await next()` does not run unless it is in a
`finally` block. The exception reaches filters only after it escapes the
middleware stack. Middleware may deliberately catch and map an exception before
filters, but broad catch-all mapping usually obscures the documented error
contract.

Provider resolution is distinct from method invocation. A request-scoped or
transient resource acquired while resolving any middleware is already owned by
the request scope even when an outer middleware does not call `next()`. It
closes during request-scope cleanup rather than being skipped by the short
circuit.

## One-Shot `next`

Every middleware receives its own async `next` callback. It may be awaited at
most once. A second call raises `PipelineStateError` and does not execute
downstream a second time.

Always await `next()` inline. Do not retain it, invoke it from detached work, or
race multiple calls. The one-shot rule protects handlers and request resources
from duplicate execution; it does not undo side effects completed by the first
call before a second-call error.

## Middleware Short Circuits

A middleware may skip all downstream work by not calling `next()`:

```python
from tori_py import HttpResponse, PipelineResult


class MaintenanceMiddleware:
    async def handle(self, context, next) -> PipelineResult:
        del context, next
        return PipelineResult.from_response(
            HttpResponse(
                b"Service temporarily unavailable.\n",
                status_code=503,
                headers={
                    "Content-Type": "text/plain; charset=utf-8",
                    "Retry-After": "60",
                },
            )
        )
```

This skips the remaining middleware `handle()` calls, guards, `@no_body`, body
binding, handler provider injection, pipes, interceptors, and the handler. All
middleware providers have already resolved, but downstream-stage providers have
not. Edge-level request limits and security controls must not depend on
downstream route dispatch.

Short-circuiting after `await next()` is different: downstream has already run,
and the middleware is replacing or transforming its result.

## Guards

A guard implements `can_activate(context) -> bool`:

```python
from tori_py.starlette import RequestContext


class ApiKeyGuard:
    async def can_activate(self, context: RequestContext) -> bool:
        return context.headers.get("x-api-key") == "configured-value"
```

This demonstrates the extension point only. Production authentication should
verify credentials through a dedicated provider, avoid hard-coded secrets, and
use a Starlette `RequestContext` only when native request access is deliberate.

Register guards globally, on a controller, or on a route:

```python
from tori_py import controller, get, use_guard, use_guards


@controller("/protected")
@use_guards(AuthenticationGuard, TenantGuard)
class ProtectedController:
    @get("/records")
    @use_guard(RecordPolicyGuard)
    async def records(self) -> list[object]:
        return []
```

Guard implementation classes can become implicit providers during compilation,
but explicit provider declarations are useful when choosing a scope or
alternate implementation.

## Guard Ordering and Failure

Guards run sequentially in global, controller, route registration order. The
complete guard provider list resolves in that order before the first
`can_activate()` call. The first `False` stops later guard method invocations and
raises `HttpException(403, "Forbidden.")`; it does not undo already-resolved
guard providers or resources. Binding has not started, so `Body()`,
`BodyStream()`, `@no_body`, and handler provider injection do not read or
resolve request arguments.

A guard exception also stops execution. Eligible exceptions pass to route,
controller, then global filters. `False` is intentionally less expressive than
raising `HttpException`; raise a safe expected exception when the policy must
set a specific status, title, detail, or header such as `WWW-Authenticate`.

ToriPy provides no authentication, authorization, CORS, CSRF, rate limiting, or
security-header implementation. Guards are an ordering and DI extension point,
not a security policy by themselves.

## Registration Ownership

- Global middleware/guard tokens resolve from root-module visibility.
- Controller and route tokens resolve from the controller's owning module.
- Provider-backed instances retain singleton, request, or transient scope.
- Direct guard instances are shared and externally owned.
- Unregistered guard classes must be visible to graph compilation; adding one
  with a fluent global method after compilation cannot create a provider.

## Testing

Record events around `next()` to assert middleware nesting and guard order. Add
separate tests for:

- middleware short-circuit with no guard, binding, or handler calls;
- middleware short-circuit where a later middleware provider resolves but its
  `handle()` method does not run;
- one-shot `next` failure;
- first guard returning `False`, with later guard providers resolved but their
  methods not running;
- guard exception mapping through route/controller/global filters;
- rejecting guard with a body stream proving no ASGI receive starts;
- request-scoped middleware/guard provider cleanup.

## Production Considerations

- Keep middleware independent of route argument details; those values do not
  exist yet.
- Make shared middleware and guard instances concurrency-safe.
- Avoid blocking I/O in any pipeline stage.
- Put expensive body parsing after policy checks, as the pipeline already does.
- Do not use caller request IDs as authentication input.
- Preserve cancellation by using `finally` for cleanup and not catching
  `BaseException`.

## Related API

`Middleware`, `Guard`, `ExecutionContext`, `PipelineResult`, `PipelineOptions`,
`PipelineStateError`, `use_middleware`, `use_guard`, `use_guards`, `middleware`,
and `guards`.

Next: [Pipes and Validation](pipes-and-validation.md).
