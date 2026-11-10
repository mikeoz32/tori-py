# WebSockets

ToriPy exposes native Starlette WebSocket connections through explicit gateway
providers. It supplies module visibility, constructor injection, one
connection-owned request scope, marker binding, pipeline execution, and
lifecycle coordination. Your handler owns the handshake and frame protocol.

The implementation follows the
[ASGI WebSocket specification](https://asgi.readthedocs.io/en/latest/specs/www.html#websocket)
and Starlette's
[WebSocket](https://www.starlette.io/websockets/) and
[WebSocketRoute](https://www.starlette.io/routing/#websocket-routing) APIs.

## Declare A Gateway

```python
from typing import Annotated

from starlette.websockets import WebSocket
from tori_py import (
    Inject,
    Path,
    Scope,
    Socket,
    injectable,
    module,
    websocket_gateway,
)


@injectable(scope=Scope.REQUEST)
class RoomSession:
    def format(self, message: str) -> str:
        return message.strip()


@websocket_gateway("/rooms/{room}")
class RoomGateway:
    async def handle(
        self,
        socket: Annotated[WebSocket, Socket()],
        room: Annotated[str, Path("room")],
        session: Annotated[RoomSession, Inject(RoomSession)],
    ) -> None:
        await socket.accept()
        message = await socket.receive_text()
        await socket.send_text(f"{room}:{session.format(message)}")
        await socket.close()


@module(providers=[RoomGateway, RoomSession])
class RoomsModule:
    pass
```

The gateway decorator does not register a global object. Add the class to one
module's `providers`. Gateway shorthand always creates a singleton; use normal
constructor injection for singleton dependencies. Bind request-scoped or
transient providers to `handle` parameters with `Inject`.

## Connection Bindings

Every parameter except `self` requires exactly one `Annotated` marker:

| Marker | Value |
| --- | --- |
| `Socket()` | Native Starlette `WebSocket` |
| `Context()` | `WebSocketContext` or compatible Starlette context subtype |
| `Path(name)` | Matched Starlette path value |
| `Query(name)` | Raw query value or repeated-value list |
| `Header(name)` | Raw header value or repeated-value list |
| `Cookie(name)` | Raw cookie value |
| `Inject(token)` | Provider resolved in the connection scope |

Exactly one `Socket()` parameter is required. `Body()` and `BodyStream()` are
HTTP-only. There is no source-name inference.

Pipes transform path, query, header, and cookie values. Socket, context, and
injected values bypass pipes.

## Pipeline And Handshake

Global, gateway, and handler pipeline declarations run in this order:

```text
middleware -> guards -> bind -> pipes -> interceptors -> handle
```

Guards run before acceptance. A guard returning `False` denies the handshake.
Middleware and interceptors wrap the complete handler lifetime. Filters run in
handler, gateway, then global order. Disconnect, disconnected-send, and task
cancellation errors bypass filters so resource cleanup and shutdown retain
their normal semantics.

The framework never accepts automatically and never encodes a handler result.
Use the native socket to choose subprotocols, receive text or bytes, send frames,
deny the handshake, and close with an application-defined code.

ToriPy closes a socket that is still open with these codes:

| Outcome | Close code |
| --- | --- |
| Handler returns normally, or a filter handles the error | 1000 |
| A guard denies the handshake or `WebSocketForbidden` is raised | 1008 |
| An unhandled exception escapes the pipeline | 1011, then the exception is re-raised |

A client disconnect is not closed again, and cancellation is re-raised
unchanged.

## Scope And Shutdown

A matched connection opens one request scope before guards and closes it after
handler return, disconnect, failure, or cancellation. Request-scoped providers
are reused within that connection and are not shared with other connections.
Long-lived sockets therefore keep their request resources open; do not hold a
database transaction for the whole connection unless that is deliberate.

During application shutdown, new connection scopes are rejected and active
connections use the same bounded drain and cancellation policy as HTTP request
scopes. Before lifespan readiness or after shutdown, the ASGI wrapper closes a
WebSocket scope with code `1013`.

## Deliberate Non-Goals

ToriPy does not provide per-message decorators, automatic JSON envelopes,
Socket.IO, rooms, broadcast registries, presence, reconnect guarantees, or
OpenAPI/AsyncAPI generation. Implement the frame protocol in application code
or add a separately owned integration.
