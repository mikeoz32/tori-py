# ToriPy LiveView Specification

This directory records the executable contract for `tori-py-liveview`.

1. The package is optional and depends on ToriPy; ToriPy core never imports it.
2. Pages are explicitly listed in `LiveViewModule.for_root`; package scans and
   process-global registries are forbidden.
3. Every page is a request-scoped provider. HTTP and WebSocket mounts resolve
   through the owning module context and support normal DI.
4. HTTP renders a complete document and signed mount token. A Channel join
   creates a fresh connected page instance and sends a complete render tree.
5. Browser interoperability targets official `phoenix@1.8.13` and
   `phoenix_live_view@1.2.11`: Phoenix V2 arrays, Channels events and replies,
   `phx-*` bindings, and Phoenix render-tree semantics.
6. Both official global minified builds are exact checksum-pinned artifacts,
   not Python-specific forks. Builds and application startup require no network.
7. Phoenix Socket receives an endpoint base and connects to its `/websocket`
   transport with `vsn=2.0.0`.
8. Inbound text frames are bounded before decoding and governed by finite join
   and idle deadlines. Binary frames are unsupported.
9. The default Origin policy is same-origin. Explicit origins are normalized
   absolute HTTP origins. Missing or malformed origins are rejected.
10. Dynamic render values are escaped unless explicitly marked trusted. Pages,
    components, and stream items accept Python 3.14 Templates; `html`,
    `fragment`, `classes`, and `attrs` provide explicit authoring boundaries.
    Nested render values remain Phoenix subtrees rather than flattened HTML.
11. Stateful components use `(concrete type, id)` identity, stable
    connection-local CIDs, update-before-render, targeted `phx-target` events,
    official component trees, and cleanup on removal or disconnect.
12. Streams use `phx-update="stream"`, Phoenix keyed comprehensions, official
    insert/delete/reset tuples, browser-owned children, insertion and limit
    semantics, disconnected contents, one-shot delivery, and reconnect reset.
13. Nested components, uploads, navigation, hooks, and server-initiated
    `send_info` remain outside the current server surface.

The complete architectural and wire contract is maintained in
`TORI_PY_LIVEVIEW_ARCHITECTURE.md`.
