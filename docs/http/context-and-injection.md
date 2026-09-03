# HTTP Context and Injection

Route handlers can receive request execution metadata through `Context()` and
request-visible providers through `Inject()`. Both are supplied after guards and
are excluded from argument pipes.

## Portable HTTP Context

Bind `HttpContext` when the handler does not require Starlette-native APIs:

```python
from typing import Annotated

from tori_py import Context, get
from tori_py.http import HttpContext


@get("/request-info")
async def request_info(
    self,
    context: Annotated[HttpContext, Context()],
) -> dict[str, str | None]:
    return {
        "application": context.application_id,
        "module": context.module_id,
        "route": context.route_id,
        "request_id": context.request_id,
        "kind": context.execution_kind,
    }
```

The portable context exposes:

| Property | Meaning |
| --- | --- |
| `application_id` | Application identifier |
| `module_id` | Owning compiled module label |
| `route_id` | `"METHOD /compiled/path"` for a matched route, otherwise `None` |
| `request_id` | Framework-selected request ID |
| `resolver` | Scoped resolver using the route's owning module visibility |
| `metadata` | Immutable HTTP metadata mapping |
| `execution_kind` | Always `"http"` |
| `request` | Opaque native request object |

Treat `request` as opaque in portable code. Accessing its Starlette methods
introduces the same dependency as annotating `RequestContext`.

## Starlette Request Context

Use `RequestContext` for an intentional Starlette dependency:

```python
from typing import Annotated

from tori_py import Context, get
from tori_py.starlette import RequestContext


@get("/native-request-info")
async def native_request_info(
    self,
    context: Annotated[RequestContext, Context()],
) -> dict[str, object]:
    return {
        "method": context.method,
        "path": context.path,
        "user_agent": context.headers.get("user-agent"),
        "query": list(context.query_params.multi_items()),
        "path_params": dict(context.path_params),
        "cookies": dict(context.cookies),
    }
```

`RequestContext` subclasses `HttpContext` and exposes the native Starlette
`Request`, headers, query parameters, path parameters, and cookies. Its
`metadata` mapping contains method, path, headers, query, and path parameters.

At application compilation, the Starlette adapter verifies that
`RequestContext` can satisfy every declared context type. A custom subclass that
the adapter does not create is rejected. Prefer the portable base unless the
handler needs native behavior.

## Current Context Access

Code reached from a handler or pipeline component may read the ambient context:

```python
from tori_py.http import current_http_context
from tori_py.starlette import current_request_context

context = current_http_context()          # HttpContext | None
native = current_request_context()        # RequestContext | None
```

Both functions return `None` outside a managed HTTP request. Explicit parameter
binding is easier to test and makes dependencies clearer; ambient lookup is
most appropriate for cross-cutting adapters and logging helpers.

## Handler Provider Injection

`Inject(token)` resolves from the current request scope using the route's owning
module visibility:

```python
from dataclasses import dataclass
from typing import Annotated

from tori_py import Inject, Scope, FactoryProvider, get, module


@dataclass(frozen=True, slots=True)
class RequestActor:
    name: str


@get("/actor")
async def actor(
    self,
    value: Annotated[RequestActor, Inject(RequestActor)],
) -> dict[str, str]:
    return {"name": value.name}


@module(
    providers=[
        FactoryProvider(
            RequestActor,
            lambda: RequestActor("anonymous"),
            scope=Scope.REQUEST,
        )
    ]
)
class ActorsModule:
    pass
```

In a complete application, the route belongs to a controller declared in the
same module or a module that can see the exported token. A request-scoped
provider is created once per request and reused for later resolutions in that
scope. A transient provider is created per resolution. Singleton providers are
shared across requests.

The annotation does not choose the token when `Inject` supplies one. For
`Annotated[RequestActor, Inject("current.actor")]`, the string token is
authoritative.

Pipeline components can use `context.resolver.resolve(token)` when resolution
is genuinely dynamic. Constructor injection remains preferable for fixed
dependencies because graph compilation can validate it before startup.

## Lifetime and Cleanup

The HTTP context and request scope stay active through:

- handler and pipeline execution;
- native Starlette response streaming and file sending;
- Starlette background tasks attached to the response;
- request-scoped managed resource cleanup.

After completion, the scope closes, its resolver is invalidated, and the
current-context variable is reset. Retaining `HttpContext`, `RequestContext`, a
resolver, or a request-scoped provider for detached work is unsafe. The resolver
is bound to the request task: another task receives `ScopeError` even while the
request is active, and resolution after cleanup raises `ScopeClosedError`. A
provider may already have released its managed resource after cleanup.

An already resolved value may be passed to a child task only when the value is
safe for that use and the request task joins the child before returning.

For work that must outlive a response, copy only immutable application data and
hand it to an application-owned queue or use a fresh `WorkScopeFactory` work
scope. Do not copy the HTTP context into that work.

## Routing Error Context

404 and 405 happen before a controller route matches. Global filters receive a
partial HTTP context:

- `module_id` identifies the root module;
- `route_id` is `None`;
- request ID and native request metadata remain available.

Route and controller filters do not run. Global components must handle
`route_id is None` rather than assuming a matched endpoint.

## Request IDs

`context.request_id` is the final validated or generated `X-Request-ID`. It is
also placed in response headers and normal request logging context. It is an
observability field only. Never derive tenant, actor, authorization, replay, or
idempotency decisions from it.

## Testing

The tested Task API demonstrates request provider injection and native context
use:

```python
--8<-- "examples/tori_py/reference_apps/task_api/app.py"
```

For focused tests:

- assert `request_id`, `route_id`, and module identity from a real HTTP request;
- resolve a request-scoped provider twice within one request and compare
  identity when that behavior matters;
- verify managed request resources close after native response background work;
- verify `current_request_context()` returns `None` after request completion;
- test stale resolver use raises the documented scope error rather than leaking
  a resource.

## Production Considerations

- Use `HttpContext` in reusable application code and isolate `RequestContext` at
  adapter boundaries.
- Keep request data out of singleton controller instance attributes.
- Make externally shared pipeline instances concurrency-safe.
- Avoid ambient context in domain services; pass stable values explicitly.
- Do not use the request ID as a security boundary.
- Keep sensitive headers and cookies out of logs and exception messages.

## Related API

`Context`, `Inject`, `HttpContext`, `current_http_context`, `RequestContext`,
`current_request_context`, `ExecutionContext`, `ScopedResolver`,
`ScopeClosedError`, `Scope`, and `WorkScopeFactory`.

Next: [Request Pipeline](../pipeline/index.md).
