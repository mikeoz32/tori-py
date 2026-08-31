# ToriPy WebSockets Implementation Plan

This plan implements
[`TORI_PY_WEBSOCKETS_ARCHITECTURE.md`](TORI_PY_WEBSOCKETS_ARCHITECTURE.md)
through the executable N9 specification.

## WS0: Contracts

- Add gateway and socket metadata without Starlette imports.
- Add transport-neutral WebSocket context and immutable plan declarations.
- Prove explicit singleton provider registration and duplicate-path validation.

## WS1: Compiler and Binding

- Discover only compiled provider classes with direct gateway metadata.
- Compile `handle` signatures once using marker-only bindings.
- Qualify pipeline provider references and bind started singleton gateways once.

## WS2: Connection Pipeline

- Execute global/gateway/handler middleware, guards, pipes, interceptors, and
  filters in an independent WebSocket executor.
- Preserve cancellation and disconnect exceptions.
- Deny guard failures before handshake acceptance.

## WS3: Starlette Adapter

- Register native `WebSocketRoute` entries beside HTTP routes.
- Open one request scope for each matched connection.
- Bind native Starlette `WebSocket`, context, handshake values, and providers.
- Extend readiness and shutdown behavior to ASGI WebSocket scopes.

## WS4: Public Surface and Verification

- Export driver-neutral declarations from `tori_py` and Starlette context
  extensions from `tori_py.starlette`.
- Add API documentation, one runnable example, and changelog entry.
- Run focused tests, the full workspace test suite, Ruff, formatting, typing,
  documentation verification, and package builds.
