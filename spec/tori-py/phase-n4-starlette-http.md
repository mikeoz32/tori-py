# Phase N4: Starlette Application and Controllers

## Purpose

Add the framework-owned `tori_py.http` execution layer and the sole v1 transport
adapter: Starlette. The HTTP layer compiles controller metadata to route plans
and owns HTTP contexts/errors. Starlette registers native routes, creates
request scopes, extracts raw HTTP input, encodes outputs, owns request IDs, and
exposes the ASGI factory/lifespan wrapper. Pipeline behavior beyond direct
handler invocation is N5.

## Entry Criteria

- N0-N3 pass.
- Application lifecycle exposes a driver-binding hook.
- Request admission, scope leases, settings, logger, and testing lifecycle are
  stable.

## Application Factory

```python
async def create_application() -> NestApplication:
    application = await NestApplication.create(
        AppModule,
        options=ApplicationOptions(...),
        pipeline=PipelineOptions(...),
        adapter=StarletteAdapter(StarletteOptions(...)),
    )
    return application.use_global_filter(ExternalFilter())


application = asgi(create_application)
```

`NestApplication` and `PipelineOptions` are imported from `tori_py`;
`StarletteAdapter`, `StarletteOptions`, and `asgi` are imported from
`tori_py.starlette`. `create()` compiles only. Calling `asgi()` is synchronous
and returns an
asynchronous ASGI3 callable. That callable awaits the factory and application
startup exactly once during ASGI lifespan startup in the server event loop.
The wrapper validates at runtime that calling the factory returns an awaitable
and that awaiting it yields a `NestApplication` configured with
`StarletteAdapter`; violations send lifespan startup failed and never start
resources.

Lifespan requirements:

- serialize startup/shutdown;
- send startup complete only after ready state;
- send startup failed with an actionable message on failure;
- invoke application shutdown exactly once;
- send shutdown failed when shutdown returns a primary failure;
- reject HTTP before readiness/after shutdown with 503 Problem Details;
- never restart one stopped application instance.

## Controller and Route Compilation

Controllers are explicit module metadata and mandatory eager singleton
providers. `tori_py.http` compiles frozen route plans from decorators/signatures
without creating Starlette objects during application compilation.

The public `compile_controller_routes(module_id, controller)` helper performs
this compilation for exactly one controller and freezes parameter plus return
annotations. Absent return metadata remains distinguishable from explicit
`None`; execution never uses return metadata for response validation or
conversion. Whole-graph route compilation delegates to the helper and retains
graph-wide duplicate checks.

At startup, bind route plans once to started singleton controller instances and
create Starlette `Route` objects in declaration order.

ToriPy does not implement route matching. It delegates overlaps, converters,
trailing-slash redirects, HEAD/OPTIONS, and Allow behavior to the pinned
Starlette version.

ToriPy normalizes joined controller/method paths only for exact duplicate
method/path detection. An exact duplicate is a bootstrap error. Non-identical
overlaps retain Starlette declaration-order behavior.

Exact duplicate normalization:

- uppercase the method;
- add one leading slash;
- collapse only the controller-prefix/method-path join boundary;
- preserve trailing slash, segment spelling, parameter names, and converter
  text;
- treat GET as reserving implicit HEAD for duplicate detection.

Therefore `/x` differs from `/x/`, and `/{id}` differs from `/{name}`. Starlette
owns their runtime behavior.

## HTTP Context and Scope

For every accepted request:

1. register the current task;
2. open one request scope and lease;
3. create `RequestContext` implementing core `ExecutionContext`;
4. bind/resolve/invoke the route;
5. await the complete Starlette response ASGI call;
6. close request resources LIFO;
7. invalidate the lease and reset context variables;
8. unregister the task.

`RequestContext` exposes normalized HTTP data plus an explicit Starlette request
extension. Core pipeline code uses only `ExecutionContext`.

Detached code retaining resolver/context cannot resolve after lease closure.

## Request IDs

Use `X-Request-ID`:

- accept one value matching `[A-Za-z0-9._-]{1,128}`;
- duplicate, absent, invalid, or oversized input generates UUIDv7;
- invalid raw values are not logged/echoed;
- expose the final ID in context/logs/response;
- overwrite a conflicting header on explicit Starlette responses.

Request IDs are observability metadata only.

## Binding Markers

Except `self`, every route parameter has exactly one marker:

- `Body()`;
- `Path(name)`;
- `Query(name)`;
- `Header(name)`;
- `Cookie(name)`;
- `Context()`;
- `Inject(token)`.

No source-name inference. `Context()` requires `HttpContext` compatibility;
the selected adapter additionally verifies that its concrete context subtype
can satisfy the annotation. `Inject` and HTTP markers are mutually exclusive.

N4 extraction is raw:

- body -> JSON-compatible primitives/mapping/list;
- path/query/header/cookie -> raw string or repeated sequence;
- context -> portable `HttpContext` or an explicitly requested compatible
  adapter subtype such as Starlette `RequestContext`;
- inject -> resolved provider value.

Typed msgspec conversion is N5's opt-in pipe. Without such a pipe a handler
receives raw extracted values.

## Body Handling

- one body marker maximum;
- require JSON media type;
- enforce `StarletteOptions.body_size_limit` while receiving chunks;
- malformed JSON -> 400 Problem Details;
- oversized body -> 413;
- unsupported media type -> 415;
- body is read at most once.

These errors occur after route match and can be handled by N5 filters once that
phase exists.

## Responses

Direct handler results in N4 support:

- primitives/mappings/sequences/dataclasses/msgspec structs encoded as JSON;
- transport-neutral `HttpResponse` with pre-encoded bytes, status, and headers;
- explicit Starlette `Response` passthrough.

`HttpResponse` accepts only final 200-599 statuses and case-insensitively unique
headers. Statuses 204/304 require empty content; transports own content-length
and transfer-encoding framing.

Stackable `@header(name, value)` metadata applies static string headers only to
ordinary ToriPy-encoded results. Explicit framework/driver responses own their
headers, dynamic headers use `HttpResponse`, and framework `X-Request-ID`
overrides every response kind.

ToriPy route status applies only to encoded values. `HttpResponse` and explicit
driver responses own status/headers except framework `X-Request-ID`, which is
overwritten to maintain correlation.

The request scope remains open through the explicit response ASGI call,
including Starlette streaming/files/background tasks. Advanced response
features are escape hatches without future-driver portability guarantees.

Track `http.response.start`. Exceptions after transmission starts are logged
and cannot be replaced with another response.

## Routing Errors

404/405 are rendered as Problem Details. N4 supplies a partial HTTP execution
context with root module and no route/controller identity. N5 will allow global
filters to handle these errors; controller/route filters never apply without a
route match.

## Base Problem Details

N4 owns reusable `HttpException` types and the base RFC 9457 renderer for 400,
404, 405, 413, 415, 500, and pre-readiness 503. N5 does not create another
renderer; it adds filter dispatch, guard/validation extensions, and routes
pipeline exceptions into this N4 service.

## Testing Integration

`TestingModule.compile(adapter=StarletteAdapter(...))` uses the same application
assembly and binder as production. High-level HTTP tests SHOULD use
`TestingApplication.http_client()` or `tori_py.testing.http_client(application)`.
The utility supplies `httpx.AsyncClient` over `ASGITransport` and requires the
`tori_py[testing]` optional dependency. HTTPX does not own lifespan in this flow
because `TestingModule.compile()` or the caller has already started the
application. Direct ASGI scope/message calls remain appropriate for low-level
transport, disconnect, streaming, and lifespan protocol tests.

Without an adapter, `TestingModule.compile()` remains driver-neutral. With
`StarletteAdapter`, controller/route shape validation runs after N3 overrides
and the returned testing application is Starlette-capable.

## Explicit Non-Goals

N4 MUST NOT:

- implement a custom router;
- infer HTTP source names;
- auto-convert raw values to annotations;
- implement custom auth/security policies;
- implement OpenAPI generation or documentation metadata;
- add first-class WebSocket/templates/static/stream APIs;
- implement middleware/guard/pipe/interceptor/filter chains beyond the direct
  invocation boundary needed for N5 extension.

## Tests

Tests MUST cover:

1. factory invoked once in lifespan event loop;
2. `NestApplication.create()` returns unstarted, opens no resources, invokes no
   hooks, and accepts no HTTP;
3. direct ASGI wrapper rejects non-awaitable factory results and awaited values
   that are not `NestApplication`;
4. startup/shutdown complete and failed messages;
5. concurrent lifespan serialization and restart rejection;
6. 503 outside readiness;
7. singleton controller binding;
8. exact duplicate route rejection, including GET/implicit HEAD conflict;
9. `/x` versus `/x/`, parameter-name, and converter variants remain distinct;
10. Starlette overlap/declaration-order behavior is not reimplemented;
11. marker signature validation and defaults make missing input optional;
12. raw body/path/query/header/cookie extraction;
13. repeated raw values;
14. body read once, limit, media type, malformed JSON;
15. request provider injection;
16. lease invalidation/stale resolver failure;
17. context variable reset;
18. JSON/dataclass/msgspec output;
19. explicit response passthrough and status/header ownership;
20. request ID valid/invalid/duplicate behavior and warning without raw value;
21. request ID overwrite on explicit response;
22. scope lifetime through background response work;
23. 404/405 Problem Details;
24. request cancellation and no concurrent resource close;
25. route-aware TestingModule compilation plus one HTTP request;
26. handler annotations are inspected only during compilation, not requests;
27. per-controller route compilation matches graph compilation;
28. return annotations distinguish absent metadata from explicit `None` without
    changing response execution;
29. core import boundary remains intact.

## Exit Criteria

N4 is complete when a module/controller application serves through Starlette
with production lifespan, request scopes, raw marker binding, response
ownership, and correlation semantics, without a ToriPy router implementation.
