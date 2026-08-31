# ToriPy WebSockets Architecture

Status: approved post-v1 extension. Executable behavior is specified by
[`spec/tori-py/phase-n9-websockets.md`](spec/tori-py/phase-n9-websockets.md).

## 1. Purpose

Add first-class native WebSocket connections to the existing ToriPy
application, dependency-injection, pipeline, and Starlette boundaries without
turning WebSockets into HTTP routes or inventing a message protocol.

The design follows the ASGI HTTP+WebSocket 2.5 specification and Starlette's
native `WebSocket` and `WebSocketRoute` APIs:

- https://asgi.readthedocs.io/en/latest/specs/www.html#websocket
- https://www.starlette.io/websockets/
- https://www.starlette.io/routing/#websocket-routing

## 2. Programming Model

```python
from typing import Annotated

from starlette.websockets import WebSocket
from tori_py import Inject, Socket, module, websocket_gateway


@websocket_gateway("/events")
class EventsGateway:
    def __init__(self, registry: ConnectionRegistry) -> None:
        self.registry = registry

    async def handle(
        self,
        socket: Annotated[WebSocket, Socket()],
        session: Annotated[ConnectionSession, Inject(ConnectionSession)],
    ) -> None:
        await socket.accept()
        await self.registry.serve(socket, session)


@module(providers=[EventsGateway, ConnectionRegistry, ConnectionSession])
class EventsModule:
    pass
```

`@websocket_gateway(path)` attaches immutable metadata and enables the class as
singleton provider shorthand. It does not register the class globally. The
class MUST appear in one module's `providers`; an explicit `ClassProvider` is
also valid but MUST retain singleton scope.

Each gateway declares exactly one directly defined asynchronous `handle`
method. Inherited handlers are not discovered. A gateway has one path and one
connection handler in N9.

## 3. Compilation Boundary

`tori_py.websocket` is transport neutral and imports no Starlette symbols. It
compiles immutable `WebSocketPlan` and `WebSocketParameterPlan` values from the
compiled provider graph. Plans retain the exact owning `ModuleId`, gateway
provider reference, unbound handler, path, parameter bindings, return
annotation, and class/handler pipeline metadata.

Compilation:

1. inspects only explicit class providers in the compiled graph;
2. selects classes with directly declared gateway metadata;
3. requires singleton scope and one async `handle` method;
4. freezes annotations and marker bindings once;
5. rejects exact duplicate normalized paths across the graph;
6. leaves non-identical overlaps and converter behavior to Starlette;
7. binds singleton gateway instances once during application startup.

Gateway discovery does not scan packages, inspect global registries, or add a
new `ModuleSpec` collection.

## 4. Parameter Bindings

Except `self`, every `handle` parameter has exactly one marker in
`typing.Annotated`:

- `Socket()` binds the adapter-native WebSocket object;
- `Context()` binds the transport-neutral `WebSocketContext` or a compatible
  adapter subtype;
- `Path(name)`, `Query(name)`, `Header(name)`, and `Cookie(name)` bind raw
  handshake values;
- `Inject(token)` resolves a provider from the connection scope.

`Body()` and `BodyStream()` are invalid for WebSockets. There is no source-name
inference. At most one `Socket()` binding is allowed and one is required.
Starlette validates that the requested socket annotation can accept its native
`WebSocket` type.

Raw handshake values pass through registered pipes. `Socket`, `Context`, and
`Inject` values do not.

## 5. Scope and Context

Every matched WebSocket connection opens one normal `RequestScope` rooted at
the gateway's owning module before guards run. It remains open while the
handler accepts, receives, sends, and closes, and closes after handler return,
disconnect propagation, or cancellation.

`WebSocketContext` implements `ExecutionContext` with:

- `execution_kind == "websocket"`;
- application, module, gateway path, and connection correlation identity;
- the invalidatable connection resolver;
- immutable handshake metadata;
- an opaque native socket extension.

The current WebSocket context uses a distinct `ContextVar`; HTTP context state
is neither copied nor exposed.

## 6. Pipeline

WebSockets use a dedicated executor while reusing common pipeline protocols,
provider qualification, and decorators. Ordering is:

```text
filter boundary(
  global middleware -> gateway middleware -> handler middleware ->
  global guards -> gateway guards -> handler guards ->
  bind raw arguments ->
  global/gateway/handler pipes per handshake-bound argument ->
  global interceptors -> gateway interceptors -> handler interceptors ->
  handle
)
```

Guards run before the application accepts the handshake. Guard denial closes
the unaccepted socket, which ASGI maps to HTTP 403. Middleware and interceptors
wrap the whole connection lifetime. Filters run handler, gateway, then global.
They may handle an exception by returning `PipelineResult`; their value is not
encoded or sent automatically.

`CancelledError`, `KeyboardInterrupt`, `SystemExit`, `WebSocketDisconnect`, and
ASGI disconnected-send failures bypass filters. The Starlette boundary
normalizes the server-specific `OSError` required by ASGI 2.4+ to
`WebSocketDisconnect`; unrelated application `OSError` instances remain
filterable. Unexpected unhandled ordinary exceptions close an accepted
connection with code 1011, or deny an unaccepted handshake, then propagate to
the server boundary without exposing details.

## 7. Starlette Delivery

The Starlette binder creates native `WebSocketRoute` objects alongside HTTP
`Route` objects. The endpoint constructs a Starlette `WebSocket`, opens the
connection scope, installs context, and invokes the dedicated executor.

Application readiness applies to both HTTP and WebSocket scopes. Before startup
or after shutdown, HTTP receives 503 Problem Details and WebSocket receives an
ASGI close with code 1013. Existing connections participate in normal request
scope drain and cancellation during shutdown.

Handlers own `accept`, `send_*`, `receive_*`, subprotocol selection, denial,
and explicit `close` policy. If a normally completed or filter-handled pipeline
leaves the socket open, the adapter sends a default code-1000 close before
ending the ASGI connection. The adapter MUST use `websocket.send()` and
`websocket.receive()` when operating at raw ASGI level so Starlette maintains
socket state.

## 8. Non-Goals

N9 does not provide:

- `@subscribe_message` or per-message handler discovery;
- `{event, data}` or any other automatic frame envelope;
- automatic JSON decoding, validation, or serialization;
- Socket.IO compatibility;
- connection registries, rooms, broadcast hubs, or presence;
- property injection such as `@WebSocketServer()`;
- automatic authentication or origin policy;
- reconnect, delivery, ordering, or persistence guarantees;
- OpenAPI or AsyncAPI generation.

## 9. Compatibility

Applications without gateway providers retain their existing HTTP behavior.
OpenAPI discovery continues to consume only compiled HTTP routes. Core imports
remain free of Starlette, and importing `tori_py` does not eagerly import the
Starlette driver.
