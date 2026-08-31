# tori-py-framework

`tori-py-framework` is the core Tori Py application framework. It provides explicit
modules, dependency injection, lifecycle management, configuration, testing
utilities, and a Starlette ASGI driver for Python 3.14 applications.

It also supports explicit singleton `@websocket_gateway` providers. Each
matched native Starlette WebSocket connection owns one request scope, supports
marker-only handshake and provider binding, and runs through the framework
pipeline while the handler retains direct control of accept, frames,
subprotocols, and close behavior.

```bash
uv add tori-py-framework
```

Optional extras provide CLI and testing dependencies:

```bash
uv add "tori-py-framework[cli,testing]"
```

The package is beta and follows independent Semantic Versioning. See the
[Tori Py documentation](https://mikeoz32.github.io/tori-py/),
[repository](https://github.com/mikeoz32/tori-py), and
[changelog](https://github.com/mikeoz32/tori-py/blob/main/CHANGELOG.md).

Routes that require an empty request stream can opt in with `@no_body`. Tori Py
checks the actual stream after guards and rejects content before pipes,
interceptors, or the handler. Cumulative content at or below the configured
limit returns 400; content above it returns 413 regardless of stream chunking.

Routes that need incremental raw bytes can bind
`Annotated[HttpBodyStream, BodyStream(max_bytes=...)]`. The explicit route limit
is independent of `StarletteOptions.body_size_limit`, which continues to bound
parsed JSON bodies. The single-consumer stream starts ASGI receiving only after
guards pass, preserves non-empty byte chunks, and returns 413 on the first chunk
that makes cumulative content exceed the route limit. It is closed when endpoint
processing ends and cannot escape into response streaming, background work, or
detached tasks. Returning successfully before the final ASGI request-body
message is consumed returns 400 before response headers.

ASGI exposes one ordered receive channel, so Tori Py does not prefetch merely to
watch for disconnect while a handler pauses between body chunks. Active-body
disconnect is observed on the next stream receive; asynchronous disconnect
monitoring begins after the final request-body message.
