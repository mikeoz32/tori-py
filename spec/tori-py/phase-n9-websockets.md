# Phase N9: First-class WebSockets

## Purpose

Add native WebSocket gateway connections to ToriPy while preserving explicit
provider registration, transport-neutral compilation, connection-owned DI
scopes, pipeline ordering, and Starlette routing ownership.

## Entry Criteria

- N0-N8 pass.
- Application request admission and exception-aware scope unwinding are stable.
- Starlette remains the sole built-in ASGI adapter.

## Required Artifacts

- gateway metadata and `Socket()` binding marker;
- immutable `WebSocketPlan` and `WebSocketParameterPlan`;
- graph and per-gateway compilation helpers;
- transport-neutral `WebSocketContext` and current-context accessor;
- dedicated WebSocket pipeline executor;
- Starlette route builder and concrete context subtype;
- public exports, docs, example, and changelog entry.

## Invariants

1. Gateway classes are explicit singleton providers, never controllers or
   globally registered objects.
2. A gateway declares one direct async `handle` method and one normalized path.
3. Signatures are inspected only during compilation.
4. Each parameter has exactly one supported marker; one `Socket()` is required.
5. `Body()` and `BodyStream()` are invalid WebSocket bindings.
6. Exact duplicate paths fail bootstrap; Starlette owns every other routing
   overlap and converter behavior.
7. Gateway instances bind once at startup and are not resolved per connection.
8. One request scope covers pre-handshake guards through complete connection
   termination and resource cleanup.
9. Guards run before acceptance; handlers own handshake and frame protocol.
10. Socket, context, and injected arguments bypass pipes.
11. Cancellation, disconnect, and disconnected-send errors bypass filters.
12. No handler result is automatically encoded or transmitted.
13. Normal or filter-handled completion closes an otherwise-open socket with
    code 1000; an explicit handler/filter close retains its selected code.
14. HTTP and WebSocket current contexts are isolated.
15. Pre-readiness WebSocket scopes close with code 1013.
16. Shutdown closes admission, drains connection scopes, then applies the
    existing bounded cancellation and cleanup policy.

## Tests

Tests MUST cover:

1. metadata immutability, duplicate decoration, and path validation;
2. explicit provider shorthand and rejection outside module providers;
3. singleton-scope enforcement;
4. missing, inherited, synchronous, variadic, and multiply bound handlers;
5. marker validation and required single socket binding;
6. duplicate and non-identical route behavior;
7. no Starlette imports from transport-neutral WebSocket modules;
8. singleton binding once at startup;
9. native socket, context, path/query/header/cookie, and injected bindings;
10. request-scoped provider reuse and LIFO cleanup for a connection;
11. exact pipeline order, short circuit, and one-shot next callbacks;
12. guard denial before acceptance;
13. pipe exclusion for socket/context/injection;
14. filter precedence and disconnect/cancellation bypass;
15. context reset and stale resolver failure after disconnect;
16. text and binary echo through direct Starlette socket APIs;
17. readiness close behavior and unmatched route behavior;
18. shutdown drain and cancellation of an active connection;
19. HTTP coexistence and unchanged OpenAPI discovery;
20. full import, type, lint, docs, test, and build gates.

## Exit Criteria

N9 is complete when an explicitly registered singleton gateway can serve a
native Starlette WebSocket across one connection-owned request scope with the
documented pipeline, cancellation, readiness, and shutdown semantics, without
introducing a message protocol or Starlette dependency into transport-neutral
modules.
