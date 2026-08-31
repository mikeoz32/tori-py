# HTTP

ToriPy separates portable HTTP declarations from the Starlette transport. A
controller declares routes and raw request bindings, `tori_py.http` owns the
execution contract, and `StarletteAdapter` performs ASGI routing, extraction,
response transmission, and request-disconnect handling.

## Minimal Application

The tested Hello World application is the smallest complete HTTP application:

```python
--8<-- "examples/tori_py/getting_started/hello_world/app.py"
```

`NestApplication.create()` compiles the graph but does not start it. The
`asgi()` wrapper starts and stops the application from ASGI lifespan events.
HTTP before startup completes or after shutdown begins receives a 503 Problem
Details response.

## Public Facades

Import declarations from the facade that owns them:

| Facade | Main HTTP API |
| --- | --- |
| `tori_py` | Controllers, routes, binding markers, `status`, `header`, `no_body`, `HttpResponse`, and pipeline declarations |
| `tori_py.http` | `HttpContext`, `HttpBodyStream`, `HttpException`, and `MsgspecValidationPipe` |
| `tori_py.starlette` | `StarletteAdapter`, `StarletteOptions`, `RequestContext`, `current_request_context`, and `asgi` |
| `tori_py.testing` | `TestingModule` and the HTTPX `http_client` |

Use portable `HttpContext` and `HttpResponse` by default. Use
`RequestContext` or a Starlette `Response` only when the application
intentionally depends on the Starlette driver.

## Request Lifecycle

For an accepted request, ToriPy:

1. Opens one request scope and establishes the request ID and a partial root
   HTTP context.
2. Delegates route matching to Starlette. A matched endpoint replaces the
   partial context with its route/module context.
3. Runs global, controller, and route middleware.
4. Runs guards.
5. Enforces `@no_body`, when declared, and binds raw arguments.
6. Runs pipes, then interceptors, then the handler.
7. Validates that a bound body stream reached its final request message.
8. Encodes the result or renders a pre-start failure.
9. Closes a bound body stream before response transmission begins.
10. Awaits the complete Starlette response, including streaming and background work.
11. Closes request-scoped resources and resets the current context.

The detailed nesting and failure boundaries are documented in
[Pipeline Ordering and Cancellation](../pipeline/ordering-and-cancellation.md).

## Deliberate Boundaries

- Starlette, not ToriPy, matches paths. Route overlaps, converters,
  trailing-slash redirects, implicit `HEAD`, `OPTIONS`, and `Allow` behavior
  follow the installed Starlette version.
- Binding is raw. An annotation such as `Annotated[int, Query("page")]` does
  not convert the query string to `int`.
- `Body()` parses JSON but does not construct the annotated model.
- Typed conversion is opt-in through a pipe, normally
  `MsgspecValidationPipe`.
- `BodyStream()` is a single-consumer, request-lifetime stream. It is not a
  reusable upload object or a response-streaming API.
- Ordinary return values are JSON-encoded. `HttpResponse` carries portable
  pre-encoded bytes; Starlette responses are driver-specific escape hatches.
- Expected failures use `HttpException` and default to RFC 9457 Problem
  Details. Unexpected exceptions are not exposed to clients.

## Configuration

`StarletteOptions.body_size_limit` controls parsed `Body()` requests and
`@no_body` enforcement. Its default is 1 MiB:

```python
from tori_py.starlette import StarletteAdapter, StarletteOptions

adapter = StarletteAdapter(
    StarletteOptions(body_size_limit=2 * 1024 * 1024)
)
```

Each `BodyStream(max_bytes=...)` route owns a separate limit; the global JSON
limit does not apply to it. Configure independent limits and timeouts at the
reverse proxy or ASGI server as defense in depth.

## Testing HTTP

`TestingModule.compile(adapter=StarletteAdapter())` starts the same application
kernel and adapter used in production. Prefer its HTTPX client for behavioral
tests:

```python
--8<-- "examples/tori_py/getting_started/first_test/test_example.py"
```

The HTTP client does not run lifespan because the testing application is
already started. Always close the testing application. Use direct ASGI
scope/message tests only for low-level chunking, disconnect, response-start,
and lifespan behavior that HTTPX cannot represent precisely.

## Guides

- [Controllers and Routes](controllers-and-routes.md)
- [Request Binding](binding.md)
- [Request Bodies and Streaming](body-streaming.md)
- [Responses and Errors](responses-and-errors.md)
- [HTTP Context and Injection](context-and-injection.md)
- [Request Pipeline](../pipeline/index.md)

## Production Checklist

- Put literal routes before overlapping parameter or catch-all routes.
- Register validation explicitly; never rely on annotations to validate input.
- Set finite body limits at both the application and edge.
- Treat `X-Request-ID` as observability metadata, not identity or authorization.
- Keep request-scoped providers and contexts inside the request lifetime.
- Let cancellation propagate and release resources in `finally` blocks or
  managed provider cleanup.
- Use a Starlette response only when its portability tradeoff is acceptable.
