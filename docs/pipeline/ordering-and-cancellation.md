# Ordering and Cancellation

This page is the exact operational model for a Starlette-backed ToriPy HTTP
request. It distinguishes route-pipeline execution, response-object creation,
ASGI response transmission, and request-scope cleanup.

## Complete Successful Order

After request admission:

1. ToriPy opens one request scope, selects the request ID, and establishes a
   partial root `RequestContext` whose `route_id` is `None`.
2. Starlette matches the route. A matched endpoint establishes its owning
   module and route context; 404/405 retain the partial context.
3. All global, controller, and route middleware providers resolve in registration
   order.
4. Global, controller, and route middleware methods enter in registration order.
5. All global, controller, and route guard providers resolve in registration
   order.
6. Guard methods run sequentially in that order.
7. If declared, `@no_body` consumes and verifies the actual stream.
8. ToriPy binds every handler argument in signature order. `Body()` parses JSON,
   `BodyStream()` creates a lazy stream, `Inject()` resolves providers, and
   `Context()` supplies the context.
9. All global, controller, and route pipe providers resolve in registration
   order.
10. For each non-context/non-injected parameter in signature order, global,
    controller, and route pipe methods transform the current value.
11. All global, controller, and route interceptor providers resolve in
    registration order.
12. Global, controller, and route interceptor methods enter in registration
    order.
13. The handler runs and its synchronous value or awaited value becomes a
     `PipelineResult`.
14. Route, controller, and global interceptors unwind.
15. Route, controller, and global middleware unwind.
16. If a body stream was bound, ToriPy verifies that its final request message
     was consumed.
17. ToriPy encodes an ordinary value or validates an explicit response and
     creates a Starlette response object.
18. The endpoint closes any bound body stream.
19. Starlette sends `http.response.start` and body messages. Native streaming,
     file sending, and response background tasks run here.
20. The request scope closes managed resources in LIFO order.
21. ToriPy resets current context/logging state and unregisters the request task.

The compact nesting is:

```text
resolve all middleware providers
global middleware in
  controller middleware in
    route middleware in
      resolve all guard providers
      guards
      no-body enforcement and raw binding
      resolve all pipe providers
      pipes
      resolve all interceptor providers
      global interceptor in
        controller interceptor in
          route interceptor in
            handler
          route interceptor out
        controller interceptor out
      global interceptor out
    route middleware out
  controller middleware out
global middleware out
body-stream completion validation
response encoding
body-stream close
ASGI response transmission and background work
request resource cleanup
```

Response encoding deliberately occurs after interceptor and middleware unwind,
so those stages can transform the final application value. A body-stream
success check occurs after middleware unwind but before encoding and response
start.

## Short-Circuit Matrix

| Stage that returns early | Work already completed | Work skipped |
| --- | --- | --- |
| Global/controller/route middleware | All middleware provider resolution and outer/current middleware entries | Remaining middleware method invocations and every downstream route stage |
| Guard returns `False` | Middleware entries, all guard provider resolution, and earlier/current guard invocations | Later guard method invocations, body read/binding, pipes, interceptors, handler |
| Interceptor | Guards, all binding and pipes, all interceptor provider resolution, and outer/current interceptor entries | Inner interceptor method invocations and handler |
| Filter handles failure | All work before the failure, plus unwinding/finally blocks | Later filter resolution/invocation and default renderer |

Middleware, guards, pipes, and interceptors each resolve their complete ordered
provider list before invoking the first method in that stage. A short circuit
skips later method invocations and prevents downstream stages from resolving; it
does not undo providers or managed resources already resolved for the current
stage. Those resources remain owned by the request scope and close during normal
scope cleanup. Filters differ: after a failure, they resolve and run one at a
time until one handles the error.

An interceptor short-circuit on a stream route does not waive full body
consumption. If the final message was not consumed, result validation raises 400.

Middleware and interceptor `next` callbacks are one-shot. A second call raises
`PipelineStateError`; it is an eligible pre-start exception and normally becomes
500 unless a filter maps it.

## Exception Flow Before Response Start

The route error boundary covers ordinary `Exception` values from middleware,
guards, binding, pipes, interceptors, handlers, body-stream validation, and
response encoding. It attempts:

1. Route filters.
2. Controller filters.
3. Global filters.
4. Default Problem Details rendering.
5. Emergency generic 500 rendering if normal error rendering/encoding fails.

An exception bypasses normal code after `await next()` as it unwinds. Use
`finally` when an exit action must happen on both success and failure.

404/405 enter a separate routing error boundary with global filters only.

## Cancellation Is Not an HTTP Error

ToriPy never converts these into responses or passes them to exception filters:

- `asyncio.CancelledError`;
- `KeyboardInterrupt`;
- `SystemExit`;
- another `BaseException` not derived from `Exception`;
- a transport-classified abort such as uncaught Starlette `ClientDisconnect`.

Application code should not catch `BaseException`. If it catches
`CancelledError` for local cleanup, cleanup must be bounded and the same
cancellation must be re-raised. Managed request resources are closed by request
scope unwinding; use `finally` for non-provider local resources.

External caller, timeout, ASGI server, and application-shutdown cancellation is
preserved. The disconnect monitor's cancellation is identity-tagged, so it does
not swallow or replace cancellation already pending from another source.

## Request-Body Disconnect Timeline

Before body EOF there is one ASGI receive owner:

- `Body()` and `@no_body` consume through Starlette's request stream.
- `BodyStream()` directly owns each receive while the handler advances it.
- An active stream sees `http.disconnect` on its next receive.
- ToriPy does not run a concurrent monitor that could prefetch a body message.

After any body consumer receives the final `http.request` message, a monitor can
take exclusive ownership of `receive`. If it observes disconnect before the
response's final body message, it cancels the request task. The request sends no
replacement response and request-scope cleanup runs.

If a route never consumes the request channel, no final request message is
observed and this post-EOF disconnect monitor is not started. Do not use request
disconnect as the only deadline for long-running bodyless handlers; configure
server/application operation timeouts appropriate to the work.

Once the final response body message has been sent, disconnect no longer cancels
Starlette response background work. The request scope remains open until that
background work returns, then cleanup runs.

## Body-Stream Cleanup

The endpoint closes `HttpBodyStream` in `finally` on success, failure, and
cancellation. Closure:

- prevents another consumer from claiming the stream;
- makes an existing iterator fail on later access;
- cancels and joins a different task blocked in receive;
- happens before the returned response starts transmission.

If a handler raises an application error after partial consumption, that error
remains controlling; the framework does not replace it with the partial-stream
400. The 400 completion check applies only to a proposed successful pipeline
result.

## Response-Start Safety

`http.response.start` commits status and headers. Before it, ToriPy can replace a
failed route result with a filter response or Problem Details. After it, a
second response would violate ASGI and is never attempted.

Failures from a native streaming iterator, file sender, send call, or response
background task may happen during or after transmission. The outer request
wrapper tracks whether response start occurred. A post-start failure emits only
a sanitized framework event and propagates; clients may observe a truncated
response or connection failure.

The sanitized event has a fixed code and a new canonical framework event ID. It
does not include caller request ID, path, query, exception text or
representation, traceback, or raw exception data.

Design native responses so all validation and likely failure happens before
returning the response object where possible. Once streaming begins, recovery is
an application protocol concern, not an HTTP status replacement.

## Shutdown Interaction

Application shutdown stops request admission, drains active work to the
configured cutoff, then cancels remaining request/work owner tasks. Request
cancellation unwinds the pipeline and scope; resources are not concurrently
closed while the request task is still using them.

Cleanup is bounded by the application's shared shutdown deadline. Code that
ignores cancellation can exhaust cleanup time, so every pipeline stage and
provider should cooperate with cancellation.

## Testing Cancellation and Safety

High-level HTTPX tests are appropriate for ordering, filter mappings, and normal
body limits. Use direct ASGI tests for protocol boundaries:

- pause between body chunks and assert there is no prefetch;
- deliver `http.disconnect` during an active stream;
- consume EOF, block the handler, then deliver disconnect and assert cleanup;
- apply unrelated external cancellation and assert its message/identity is
  preserved;
- return a response that raises after `http.response.start` and assert no second
  start message is sent;
- attach background work and assert the request scope remains active until it
  completes;
- return after partial body-stream consumption and assert 400 occurs before any
  proposed native response/background work starts.

Use time-bounded synchronization events in these tests. Do not depend on sleeps
or a particular HTTP client's chunk aggregation.

## Production Checklist

- Keep cancellation paths side-effect safe and idempotent where practical.
- Use bounded `finally` cleanup and managed providers.
- Add explicit operation deadlines for long-running handlers.
- Never detach body consumption or request-scoped work.
- Validate before starting a streaming response.
- Expect clients to receive partial bytes if transmission fails after start.
- Monitor fixed framework emergency event codes without expecting sensitive
  exception context in those records.

## Related API

`PipelineResult`, `PipelineStateError`, `HttpBodyStream`, `HttpException`,
`ApplicationOptions`, `ExecutionContext`, `ExceptionFilter`, and Starlette
`RequestContext`/`Response` escape hatches.

Next: [Responses and Errors](../http/responses-and-errors.md).
