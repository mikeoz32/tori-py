# Request Bodies and Streaming

ToriPy provides three explicit request-body policies. Choose one per route:

| Policy | Purpose | Limit |
| --- | --- | --- |
| `Body()` | Parse one JSON document into raw JSON-compatible Python values | `StarletteOptions.body_size_limit` |
| `BodyStream(max_bytes=N)` | Consume raw ASGI body bytes with direct backpressure | Route-specific `N` |
| `@no_body` | Require the actual request stream to be empty | `StarletteOptions.body_size_limit` |

A route may have at most one body binding. `@no_body` cannot be combined with
either `Body()` or `BodyStream()`.

## Parsed JSON Bodies

`Body()` requires `application/json` or a media type ending in `+json`. The
adapter counts actual received bytes, not `Content-Length`, and returns 413 when
the cumulative body exceeds the configured global limit. It then parses JSON
once. The result is still a raw dictionary, list, scalar, or `None` until a pipe
converts it.

```python
from tori_py.starlette import StarletteAdapter, StarletteOptions

adapter = StarletteAdapter(
    StarletteOptions(body_size_limit=512 * 1024)
)
```

The limit must be a non-negative, non-boolean integer. A zero limit accepts no
JSON bytes, which also means no valid JSON document can be parsed.

## Raw Body Streams

Use the exact portable stream annotation with a route-specific limit:

```python
from hashlib import sha256
from typing import Annotated

from tori_py import BodyStream, post
from tori_py.http import HttpBodyStream


@post("/artifacts")
async def upload(
    self,
    body: Annotated[HttpBodyStream, BodyStream(max_bytes=20 * 1024 * 1024)],
) -> dict[str, object]:
    digest = sha256()
    size = 0
    async for chunk in body:
        size += len(chunk)
        digest.update(chunk)
    return {"size": size, "sha256": digest.hexdigest()}
```

`BodyStream.max_bytes` must be a non-negative, non-boolean integer and may be
zero. The global JSON body limit does not apply. The marker does not require or
interpret a media type.

## Streaming Semantics

The Starlette implementation has strict request-lifetime behavior:

- Guards run before the stream is bound. A rejecting guard does not start ASGI
  body receiving.
- Binding is lazy. The first iteration step performs the first receive.
- Every iteration step directly awaits the next ASGI message. ToriPy has no
  producer queue and does not prefetch a second message while the consumer is
  paused.
- Chunk boundaries come from the ASGI server and are not application record
  boundaries.
- The limit is cumulative. If one message crosses the limit, ToriPy raises 413
  before yielding that message's chunk.
- The stream does not parse, decode, spool, rewind, or retain an extra request
  message.
- `Content-Length` does not determine acceptance; only received bytes count.
- `__aiter__()` can be claimed once. A second consumer or second iteration raises
  `RuntimeError`.
- A successful pipeline result is accepted only after the consumer receives the
  final `http.request` message. Returning early produces 400 Problem Details:
  `Request body stream was not fully consumed.`
- The endpoint calls `aclose()` on every success, error, or cancellation before
  a response object transmits bytes or starts background work. Later access
  fails deterministically.

If another task is blocked while consuming the stream, close cancels and joins
that task. Do not detach body consumption from the request handler. Consume it
in the request task and finish before returning a successful result.

Calling `aclose()` yourself does not mark a partial stream complete. If an
application intentionally aborts an upload, raise an appropriate exception and
let framework cleanup close the stream rather than returning success.

## Backpressure and Disconnects

ASGI exposes one ordered receive channel. While a body is active, the consumer's
next iteration observes `http.disconnect`. ToriPy cannot concurrently watch for
disconnect without stealing and buffering the next body message, so it
deliberately preserves direct backpressure: if the handler pauses between
non-final chunks, disconnect observation waits until it asks for the next chunk.

After the final body message, a dedicated monitor takes exclusive ownership of
the receive channel and may cancel the request task if the client disconnects
before response completion. External timeout, server, and shutdown cancellation
is identity-preserved and is not mistaken for monitor cancellation.

An uncaught Starlette `ClientDisconnect` bypasses exception filters and response
rendering. Cleanup still closes the body stream and request scope. See
[Ordering and Cancellation](../pipeline/ordering-and-cancellation.md).

## Routes That Reject Bodies

Use `@no_body` when an endpoint contract requires an empty actual stream:

```python
from tori_py import HttpResponse, no_body, post


@post("/members/refresh")
@no_body
async def refresh(self) -> HttpResponse:
    return HttpResponse(b"", status_code=204)
```

The check runs after guards and before argument extraction, pipes,
interceptors, or the handler. It consumes through EOF or cumulative limit
overflow:

- empty actual stream: continue;
- non-empty content at or below `body_size_limit`: 400;
- content above `body_size_limit`: 413.

Headers alone do not decide whether a body exists. A false `Content-Length: 0`
does not hide bytes, and a nonzero `Content-Length` with an empty actual stream
does not cause rejection.

Global, controller, or route middleware wraps the guard/binding stage. A
middleware that short-circuits before calling `next()` also bypasses
`@no_body`, because downstream request dispatch never occurs. Edge body limits
must therefore remain independent of route dispatch.

## Pipes and Body Streams

The current executor applies pipes to every bound route parameter except
`Context()` and `Inject()`. That includes `BodyStream()`. A global
`MsgspecValidationPipe` cannot meaningfully convert `HttpBodyStream` to its
protocol annotation and will report validation failure.

For applications combining global conversion and streaming routes, use a custom
front pipe that returns the value unchanged when
`metadata.binding_kind == "body_stream"`, or register conversion only on the
controllers/routes that bind parsed values.

## Failure Behavior

| Failure | Result |
| --- | --- |
| Parsed body uses a non-JSON media type | 415 Problem Details |
| Parsed JSON is malformed or empty | 400 Problem Details |
| Parsed body exceeds global limit | 413 Problem Details |
| Raw stream exceeds route limit | 413 Problem Details |
| Successful result after partial stream consumption | 400 Problem Details before response start |
| Handler raises while stream is partial | Handler error remains controlling; stream closes |
| Client disconnects during active receive | Abort propagates without filter rendering |

## Testing

Use normal HTTPX tests for parsed body media types, validation, and limits. Use a
direct ASGI test with multiple `http.request` messages to prove chunk
preservation, backpressure, cumulative limits, partial consumption, and
disconnect behavior. Assertions based on one HTTP client's chunk layout are not
portable because the ASGI server controls message size.

Always assert that a stream route consumes EOF on success. Test zero, exact
limit, and limit-plus-one cases independently.

## Production Considerations

- Configure reverse-proxy and ASGI-server request limits in addition to ToriPy
  limits.
- Configure finite upload and idle timeouts outside this API; ToriPy's stream
  marker is a byte limit, not a deadline.
- Treat chunks as arbitrary bytes. Build explicit incremental parsers with their
  own complexity and record-size bounds when needed.
- Do not launch detached work that retains `HttpBodyStream`, `HttpContext`, or a
  request-scoped resolver.
- Persist or enqueue a completed, application-owned artifact before returning;
  do not hand the request stream to later background work.
- Prefer the portable stream contract unless code intentionally needs
  Starlette's `ClientDisconnect` type.

## Related API

`Body`, `BodyStream`, `HttpBodyStream`, `no_body`, `StarletteOptions`,
`HttpException`, and `MsgspecValidationPipe`.

Next: [Responses and Errors](responses-and-errors.md).
