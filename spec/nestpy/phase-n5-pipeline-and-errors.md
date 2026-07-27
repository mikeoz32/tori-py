# Phase N5: HTTP Pipeline and Errors

## Purpose

Implement the full global/controller/route execution pipeline, typed conversion
through pipes, and exception filters while preserving cancellation and
response-transmission safety. Reuse and extend N4's base Problem Details
renderer rather than creating a second renderer.

## Entry Criteria

- N4 direct route invocation, scopes, contexts, binding, and response ownership
  pass.
- Pipeline declarations/protocols from N0 are stable.

## Qualified Pipeline Providers

Middleware declarations are provider tokens. Guard, pipe, interceptor, and
filter declarations accept provider tokens, implementation classes, or
preconstructed protocol instances.

Application-wide registrations are declared through driver-neutral
`PipelineOptions`; they are not Starlette transport options.
After compilation and before startup, an application factory may append
bindings through `NestApplication.use_global_guard()`,
`use_global_pipe()`, `use_global_interceptor()`, and `use_global_filter()`.
Preconstructed instances are externally owned and are not resolved, initialized,
or closed by DI. Provider tokens and registered class tokens are accepted only
when visible from the compiled root module and retain DI scope and lifecycle
ownership. Unregistered implementation classes remain `PipelineOptions`
registrations so fallback providers can be created during compilation. Calling
these methods after startup is an application-state error.

Provider fallback discovery, registration qualification, guards, pipes,
interceptors, filters, and one-shot pipeline execution are framework-owned.
Concrete transport adapters MUST NOT implement their ordering or DI resolution.
An HTTP adapter supplies native request binding, response rendering, and abort
classification through narrow callbacks/ports.

- global tokens are qualified once against compiled root-module visibility
  before binding, including each fluent configuration snapshot;
- controller and route tokens resolve from the owning module;
- unregistered implementation classes become implicit class providers in the
  declaring module and retain normal DI, scope, and lifecycle behavior;
- any explicit provider visible for the class token takes precedence over
  implicit registration;
- preconstructed instances are shared and externally owned; the framework does
  not inject into, scope, initialize, or clean them up;
- compiled plans store qualified provider references;
- runtime never resolves an unqualified global token from a route module;
- request-scoped and transient pipeline providers are allowed and owned by the
  request scope.

`use_guard`, `use_pipe`, `use_interceptor`, and `use_filter` are singular
convenience decorators. Their plural forms accept one or more ordered
registrations. Middleware remains provider-token based rather than adopting the
class-or-instance enhancer contract.

## Execution Order

After route match/request scope creation:

```text
filter boundary(
  global middleware -> controller middleware -> route middleware ->
  global guards -> controller guards -> route guards ->
  bind raw arguments ->
  global/controller/route pipes per HTTP-bound argument ->
  global interceptors -> controller interceptors -> route interceptors ->
  handler -> response encoding
)
```

404/405 use global filters only with partial context.

Registration order is tuple order at each level. Repeating the same pipeline
decorator kind on one controller/route is a bootstrap error.

## Middleware and Interceptor Next

`Next` is a one-shot async callable. Its second invocation raises
`PipelineStateError`. Middleware/interceptors nest in registration order and
unwind in reverse order. They may short-circuit with a `PipelineResult`.

## Guards

Guards run sequentially. First `False` raises standard forbidden
`HttpException`. Exceptions continue to filters. Nestpy provides no built-in
authentication implementation.

## Binding and Pipes

N4 binding extracts all raw values before pipes run.

Pipes execute per HTTP-bound argument in handler parameter order:

1. global pipes;
2. controller pipes;
3. route pipes.

`Context()` and `Inject()` arguments never pass through pipes.

Provide opt-in `MsgspecValidationPipe`:

- converts raw value to declared annotation;
- handles scalar/repeated/body conversion;
- emits structured validation errors;
- does not run automatically unless registered;
- supports dataclasses/msgspec structs and msgspec-compatible types.

There is one conversion point: the pipe. Binding does not pre-convert.

## Filters and Cancellation

Filters accept `Exception`, not `BaseException`.

The framework MUST always propagate:

- `asyncio.CancelledError`;
- `KeyboardInterrupt`;
- `SystemExit`;
- any other `BaseException` not derived from `Exception`.

Filter order is route, controller, global. A filter handles by returning a
`PipelineResult`; re-raising selects the next filter. A filter's own `Exception`
also proceeds to the next filter. The default renderer runs last.

Global filters may receive routing 404/405 through partial context. Route and
controller filters require a successful match.

No replacement response is attempted after `http.response.start`; such errors
are logged with request ID and propagated/observed according to ASGI behavior.

## Problem Details

Default content type is `application/problem+json`. Include:

- `type`;
- `title`;
- `status`;
- `detail`;
- `instance`;
- optional structured `errors` extension.

Default mappings:

- malformed/missing/validation input -> 400;
- guard false -> 403;
- unmatched path -> 404;
- method not allowed -> 405 with Starlette Allow header;
- oversized body -> 413;
- unsupported media type -> 415;
- unexpected `Exception` -> 500 with generic detail.

Unexpected exceptions are logged with traceback and request ID, never returned
with source details.

## Explicit Responses

Handlers, middleware, and interceptors may return portable `HttpResponse`
values. Filters may wrap one in `PipelineResult.from_value()`. Opaque explicit
Starlette responses remain a driver escape hatch. Framework route status does
not alter either response kind; request ID overwrite and request-scope lifetime
remain N4 invariants.

## Explicit Non-Goals

N5 MUST NOT:

- catch cancellation in filters;
- add auth implementations;
- create detached background cleanup;
- add automatic MsgspecValidationPipe registration;
- mutate `Context` or `Inject` arguments through global pipes;
- replace a response after transmission starts.

## Tests

Tests MUST cover:

1. exact global/controller/route ordering for every pipeline kind;
2. nested unwind order;
3. one-shot `Next` rejection;
4. middleware/interceptor short circuit;
5. guard false and guard exceptions;
6. per-argument pipe order;
7. context/inject exclusion from pipes;
8. raw input without validation pipe;
9. msgspec conversion/validation with pipe;
10. no double decoding;
11. route/controller/global filter precedence;
12. filter fallthrough and filter failure;
13. default Problem Details mappings;
14. global 404/405 filtering;
15. cancellation bypasses catch-all filters;
16. client disconnect cancellation;
17. KeyboardInterrupt/SystemExit bypass;
18. response encoding failure before start is filterable;
19. failure after response start is logged, not re-rendered;
20. pipeline provider scopes/resources clean once;
21. root-qualified global pipeline provider wins even when route module binds
    the same unqualified token;
22. duplicate same-kind pipeline decorator rejection;
23. `ArgumentMetadata` exposes parameter, binding, source, annotation, route,
    and module fields;
24. request ID is preserved across all responses/errors.

## Exit Criteria

N5 is complete when every post-match failure and routing 404/405 follows the
documented filter/default-renderer contract, typed conversion occurs only in
pipes, and cancellation cannot be swallowed by user filters.
