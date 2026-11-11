# ToriPy LiveView Specification

This directory records the executable contract for `tori-py-liveview`.

1. The package is optional and depends on ToriPy; ToriPy core never imports it.
2. Pages are explicitly listed in `LiveViewModule.for_root`; package scans and
   process-global registries are forbidden.
3. Every page is a request-scoped provider. HTTP and WebSocket mounts resolve
   through the owning module context and support normal DI.
 4. HTTP renders a complete document and signed mount token. A Channel join
    creates a fresh connected page instance and sends a complete render tree.
    `mount` runs before `handle_params` on every HTTP and Channel mount.
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
 13. `send_info` uses a bounded connection-local queue. Info callbacks, browser
    events, renders, and outbound writes are serialized on the WebSocket task;
    successful callbacks emit unreferenced Phoenix `diff` pushes, and disconnect
    detaches the queue and rejects later sends.
 14. Nested components, child LiveViews, uploads, and `stream_async` remain
    outside the current server surface.
 15. `@live_view` accepts `action` and `session` and may be stacked for several
    paths on one page class. `mount` runs before `handle_params` on every HTTP
    and Channel mount. `push_patch` navigates within the page, `push_navigate`
    navigates within the session, and other sessions or unknown targets fall
    back to a full reload. `LiveSession` groups routes with shared `on_mount`
    hooks; authorization lives in hooks, `mount`, and `handle_params`, never in
    the HTTP pipeline alone.
 16. The bootstrap passes `globalThis.ToriLiveHooks` to the official `LiveSocket`
    as its `hooks` object; hook events reach `handle_event` unchanged.
    `push_event` queues validated JSON-object payloads delivered once under the
    top-level `e` render key, with `true` marking before-patch dispatch. A
    `handle_event` mapping result becomes the top-level `r` key of its reply
    diff. `send_update` updates rendered components in order before the next
    render. Pushed events and updates are discarded with rejected events, the
    disconnected render, and disconnect; pushed events and replies also drop
    when a handler navigates away.
 17. `put_flash` flash follows `push_navigate` as a signed `flash` token that the
    next join returns, and `redirect` through the official `__phoenix_flash__`
    cookie that the HTTP render verifies and deletes. Flash tokens expire after
    60 seconds and never verify as mount tokens. Handler navigation carries the
    flash put since the last render; navigation while mounting carries the whole
    flash, so received flash passes through a page that moves on. The
    disconnected render's flash seeds only the document's first connected mount.
    `lv:clear-flash` clears a kind or all flash before page or component
    handlers.
 18. `start_async` and `assign_async` run only when connected, deliver one
    `AsyncResult` per task on the WebSocket task, drop replaced work, report
    cancellation as `asyncio.CancelledError`, and cancel work with its page or
    component, waiting at most `async_cancel_timeout_seconds` for cancelled
    work. A component's work stops before its `disconnect` hook. A raising
    `handle_async` closes with `1011`.
 19. The bootstrap passes the official client a params function returning a
    fresh copy of `globalThis.ToriLiveParams`, so the client's join fields never
    reach the WebSocket URL. Connected mounts receive the join params as
    `MountContext.connect_params`; `static_changed` compares `_track_static`
    URLs by path and query. A 4xx `HttpException` anywhere in the connected
    join, from on-mount hooks through patches the mount queued and the join
    render, answers the join with `{reason: "reload", status, token}`. The reloaded HTTP
    request carrying that token in `__phoenix_reload_status__` answers with the
    same status for the same page and resource, so the browser reloads at most
    once.

The complete architectural and wire contract is maintained in
`TORI_PY_LIVEVIEW_ARCHITECTURE.md`.
