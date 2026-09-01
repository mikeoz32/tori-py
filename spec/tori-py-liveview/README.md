# ToriPy LiveView Specification

This directory records the executable contract for `tori-py-liveview`.

1. The package is optional and depends on ToriPy; ToriPy core never imports it.
2. Pages are explicitly listed in `LiveViewModule.for_root`; package scans and
   process-global registries are forbidden.
3. Every page is a request-scoped provider. HTTP and WebSocket mounts resolve
   through the owning module context and therefore support normal DI.
4. HTTP renders a complete document and a signed mount token. WebSocket join
   creates a fresh connected page instance and always sends a full snapshot.
5. Protocol version 2 and all `opal:*`/`data-opal-*` names are preserved.
6. Browser JavaScript is an exact pinned Opal artifact, not a Python-specific
   fork. Builds and application startup require no network access.
7. Inbound frames are text JSON, bounded before decoding, validated by message
   type, and governed by finite join and idle deadlines.
8. The default Origin policy is same-origin. Explicit origins are normalized
   absolute HTTP origins. Missing or malformed origins are rejected.
9. Python 3.14 templates map their strings and escaped interpolations to the
   structural render contract. Nested templates and explicitly marked markup are
   trusted composition boundaries; finite iterables compose as positional
   fragments.
10. Stateful components use `(concrete type, id)` identity, stable
    connection-local targets, update-before-render, targeted events, and cleanup
    on removal or disconnect.
11. Streams preserve Opal's ordered insert/update/delete/reset message shapes,
    browser-owned containers, item-ID validation, insertion and limit semantics,
    disconnected contents, one-shot delivery, and reconnect reset behavior.
12. `send_info` uses a bounded connection-local queue. Info callbacks, browser
    events, renders, and outbound writes are serialized on the WebSocket task;
    disconnect detaches the queue and rejects later sends.
13. Nested components, uploads, navigation, and server hook/reply APIs remain
    outside the server surface. Reserved protocol fields retain their Opal
    meaning.

The complete architectural and wire contract is maintained in
`TORI_PY_LIVEVIEW_ARCHITECTURE.md`.
