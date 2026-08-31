# Interceptors and Filters

Interceptors wrap handler execution after arguments have been bound and piped.
Exception filters map eligible failures after they escape the active pipeline.

## Interceptors

An interceptor can inspect context, call the handler chain once, and transform
the resulting `PipelineResult`:

```python
from tori_py import ExecutionContext, PipelineResult


class EnvelopeInterceptor:
    async def intercept(
        self,
        context: ExecutionContext,
        next,
    ) -> PipelineResult:
        result = await next()
        if result.is_response:
            return result
        return PipelineResult.from_value(
            {
                "data": result.value,
                "request_id": context.request_id,
            }
        )
```

Preserve `is_response` results unless the interceptor intentionally owns native
response replacement. Treating an opaque Starlette response as application
data causes response validation or JSON encoding failure.

Register interceptors globally, on a controller, or on a route with
`PipelineOptions`, `use_interceptor`, or `use_interceptors`.

## Interceptor Order and Short Circuits

Interceptors enter global, controller, route and unwind route, controller,
global. Their `next` callback is one-shot; calling it twice raises
`PipelineStateError`.

An interceptor that does not call `next()` skips the remaining interceptors and
handler. Guards, `@no_body`, argument extraction, provider injection, and pipes
have already run. For a `BodyStream()` parameter, an interceptor short-circuit
still must account for the full-consumption rule: if no stage consumed the final
body message, the proposed result is replaced by 400 before response start.

If the handler or an inner interceptor raises, code after `await next()` does
not run unless protected by `finally`. Filters run only after the exception
escapes the interceptor and middleware stacks.

## Exception Filters

A filter accepts the original `Exception` and returns a replacement
`PipelineResult` only for failures it understands. It must re-raise unknown
errors:

```python
import msgspec
from tori_py import HttpResponse, PipelineResult


class VersionConflict(Exception):
    pass


class VersionConflictFilter:
    async def catch(self, error, context) -> PipelineResult:
        if not isinstance(error, VersionConflict):
            raise error
        body = msgspec.json.encode(
            {
                "type": "about:blank",
                "title": "Conflict",
                "status": 409,
                "detail": "The record was modified by another request.",
            }
        )
        return PipelineResult.from_response(
            HttpResponse(
                body,
                status_code=409,
                headers={"Content-Type": "application/problem+json"},
            )
        )
```

Wrapping `HttpResponse` is required for a filter because the filter protocol
returns `PipelineResult`. Under Starlette, a filter may also return a native
Starlette `Response` directly, but that is an adapter-specific convenience.
Portable filters should return `PipelineResult`.

For default Problem Details from application code, prefer raising
`HttpException` at the source. Use a filter when translating a specific domain
or infrastructure exception that should not depend on HTTP.

## Filter Precedence

For a matched route, filters are tried in this order:

1. Route filters in registration order.
2. Controller filters in registration order.
3. Global filters in registration order.
4. Default Problem Details renderer.

The first valid result handles the exception. Re-raising, returning an invalid
value, failing to resolve the filter provider, or raising another ordinary
`Exception` causes a sanitized framework event and continues to the next
eligible filter. Later filters still receive the original pipeline exception,
not the filter's failure.

Use one ordered decorator for each target:

```python
from typing import Annotated

from tori_py import Path, get, use_filters


@get("/{record_id}")
@use_filters(VersionConflictFilter, RecordNotFoundFilter)
async def get_record(
    self,
    record_id: Annotated[str, Path("record_id")],
) -> object:
    return await self.records.get(record_id)
```

Applying the same pipeline-kind decorator twice to one controller or method is
a bootstrap error. This prevents Python decorator stacking from silently
reversing intended registration order.

## Routing Errors

404 and 405 happen without a matched route plan. Only global filters run, and
`context.route_id` is `None`. The 405 `HttpException` carries Starlette's
`Allow` header; preserve it when returning a custom response.

Controller and route filters do not apply merely because a request path
resembles their prefix or pattern.

## What Filters Can Catch

Before response start, matched-route filters can receive ordinary `Exception`
values from:

- middleware;
- guards;
- `@no_body` and argument binding;
- request provider resolution;
- pipes;
- interceptors;
- handlers;
- body-stream result validation;
- result normalization and JSON encoding.

Filters never receive `asyncio.CancelledError`, `KeyboardInterrupt`,
`SystemExit`, other non-`Exception` `BaseException` values, or transport aborts
such as an uncaught Starlette `ClientDisconnect`.

Native response transmission starts after the route pipeline returns its
Starlette response object. A native response failure before start may reach the
Starlette routing error boundary and global filters, but route/controller
filter replacement is no longer guaranteed. After `http.response.start`, no
filter can safely replace the response.

## Default Rendering and Filter Failure

An unhandled `HttpException` retains its safe status, title, detail, allowed
headers, and optional structured errors. Another unhandled `Exception` becomes
500 Problem Details with `Internal server error.` and no source details.

Filter resolution and execution failures are logged only as fixed framework
event codes with new event IDs. The framework log omits request data, caller
request IDs, exception text, representations, and tracebacks. A filter must log
domain information itself when appropriate, with explicit redaction.

If normal error-response encoding fails, ToriPy attempts a minimal emergency
500 response before response start. If that renderer also fails, the failure
propagates. Cancellation and process-control exceptions are always preserved.

## Testing

Test each mapping and precedence boundary:

- route filter handles before controller/global;
- re-raised error reaches the next filter;
- failing or unresolvable filter falls through;
- unexpected exception renders generic 500;
- global filter receives 404/405 with `route_id is None`;
- cancellation and disconnect never call catch-all filters;
- JSON encoding failure before start is filterable;
- native response failure after start is not replaced.

Assert safe response fields and fixed event codes, not secret exception text or
random framework event IDs.

## Production Considerations

- Keep filters narrow and re-raise errors they do not own.
- Preserve protocol headers such as `Allow`, `Retry-After`, and
  `WWW-Authenticate` when mapping errors.
- Return stable Problem Details; do not expose database, validation-library, or
  upstream exception internals unless explicitly sanitized.
- Make shared filter and interceptor instances concurrency-safe.
- Use `finally` for metrics or cleanup that must run when downstream fails.
- Never catch `BaseException` to make cancellation look like a successful HTTP
  response.

## Related API

`Interceptor`, `ExceptionFilter`, `PipelineResult`, `HttpResponse`,
`HttpException`, `PipelineStateError`, `use_interceptor`, `use_interceptors`,
`use_filter`, `use_filters`, `interceptors`, and `filters`.

Next: [Ordering and Cancellation](ordering-and-cancellation.md).
