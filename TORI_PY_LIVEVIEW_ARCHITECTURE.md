# ToriPy LiveView Architecture

## 1. Purpose

`tori-py-liveview` provides server-rendered interactive pages for ToriPy. The
Python server implements the browser-facing contracts used by the official
Phoenix 1.8.13 and Phoenix LiveView 1.2.11 JavaScript clients through ToriPy's
public module, provider, HTTP, and native WebSocket APIs.

Python owns page lifecycle, dependency injection, event dispatch, render-tree
encoding, token verification, and transport limits. The unchanged official
JavaScript owns browser event binding, Channels transport, DOM patching,
component targeting, stream application, and reconnect behavior.

## 2. Package Boundary

```text
tori-py-liveview -> tori-py-framework, starlette
tori-py-framework -X-> tori-py-liveview
```

The package is separately installable and typed. ToriPy core contains no
LiveView metadata, rendering, or protocol behavior. The integration uses
Starlette's public request and WebSocket types because it implements an ASGI
browser transport.

Applications explicitly pass page classes to `LiveViewModule.for_root`. The
package does not scan modules, installed distributions, or the filesystem and
does not use a process-global page registry.

## 3. Public Programming Model

### 3.1 Pages

`@live_view(path)` attaches immutable route metadata directly to one `LiveView`
subclass. The decorator accepts an optional `action` and `session` name and may
be stacked to map several paths to one page class. `LiveView` exposes:

- `mount(context)` for disconnected and connected initialization;
- `handle_params(params, uri)` after every mount and on every live patch, with
  merged path/query params and the full client URL;
- `live_action` carrying the matched route action;
- `push_patch(to, kind="push")` for in-page navigation applied after render;
- `push_navigate(to, kind="push")` for live navigation to another page in the
  same session, falling back to a full reload across sessions;
- `redirect(to)` for navigation with a full page reload; the target is cleaned
  like a browser reads it, must be a path or an http(s) URL, and must stay on
  the request host name or a host in `LiveViewOptions.redirect_hosts`, so
  untrusted values such as `next` cannot run script or leave the site;
- `handle_event(event, value)` for connected browser events, optionally
  returning a JSON-object reply;
- `handle_info(name, value)` for serialized timer and subscription messages;
- `send_info(name, value=None)` for connection-local message delivery;
- `push_event(event, payload=None, dispatch="after")` for a browser event
  delivered with the next render;
- `send_update(component_type, component_id, assigns=None)` for updating a
  rendered stateful component before the next render;
- `flash`, `put_flash(kind, message)`, and `clear_flash(kind=None)` for flash
  messages that follow `push_navigate` and `redirect`;
- `start_async(name, function)`, `assign_async(name, function, reset=False)`,
  `cancel_async(name)`, and `handle_async(name, result)` for concurrent work
  delivered back on the connection task;
- `render()` returning a Python 3.14 `Template`, `Rendered`, or trusted static
  HTML as `str`;
- `title()` returning an optional document title;
- `disconnect()` for connected-session cleanup;
- `render_document(live_root, client_script)` for document customization.

`UnknownEventError` declares an unsupported event. It produces a successful
no-render Channel reply carrying the reason, so the official client releases
the originating element's loading/lock refs without advancing page state. Other
handler exceptions terminate the connection with close code `1011`.
`UnknownInfoError` declares an unsupported server message and is a server
failure, so it terminates the connection with close code `1011`.
`UnknownAsyncError`, raised by the default `handle_async`, is likewise a server
failure.

### 3.2 Mount context

`MountContext` contains the native request or socket, immutable path params, the
signed resource URL, a `connected` flag, parsed query params, and
`connect_params`.

The HTTP mount receives `connected=False` and `connect_params=None`. A
successful Channel join receives `connected=True` and a read-only snapshot of
the join's `params` object, mirroring Phoenix `get_connect_params`. The official
client fills it with application params plus `_mounts`, `_mount_attempts`,
`_track_static`, and `_live_referer` (the previous URL after live navigation).
These are browser-supplied values, not authenticated data. `tracked_static`
lists the URLs of the document's `phx-track-static` elements, and
`static_changed(current)` reports whether one of them is missing from the
application's current asset URLs, comparing path and query like Phoenix
`static_changed?`; it is false when disconnected or when nothing is tracked.

These mounts use distinct request-scoped page instances. Signed params,
resource, and flash data, rather than in-process object identity, are the
transfer boundary.

### 3.3 Stateful components

`LiveComponent` exposes synchronous `mount`, `update(assigns)`, and `render`
hooks plus asynchronous `handle_event` and `disconnect` hooks. `id` is the
caller-provided stable identity. `myself` is the positive connection-local CID
placed in `phx-target`. `connected` identifies the HTTP or WebSocket lifecycle.
A component `handle_event` may return a reply like a page handler, and
`push_event`, `send_update`, `put_flash`, and `clear_flash` delegate to the
owning page. Component `start_async`, `assign_async`, and `cancel_async` run
work owned by the component: results reach the component's `handle_async` or
attribute, and removal or disconnect of the component cancels its work. Calling
any of them on a component that is not attached raises `LiveViewError`.

`LiveView.live_component(component_type, id, assigns, factory=...)` may only run
while the page renders. Identity is the concrete component type plus `id`. The
first render constructs and mounts one instance; every render updates its
assigns before rendering. Reusing the identity preserves state. Rendering one
identity twice in a page render is an error.

`LiveComponent.live_component` renders a nested component from a component's
`render` and delegates to the owning page. Nested components belong to the page
like any other: identity is unique across the whole page render at every depth,
CIDs share the page's namespace, and `phx-target`, `send_update`, async work,
and destruction work unchanged. The parent's tree holds the child's CID, and
every component tree sits flat under `c`. A child the parent stops rendering, or
every child of a parent the page stops rendering, becomes pending and follows
the destruction handshake below; the client reports each removed component.

The encoder places integer CID references in the parent tree and component
trees under the Phoenix `c` map. Component trees carry `r: 1`, allowing the
official client to add `data-phx-component` and `data-phx-view` to their single
root elements. Component markup must use explicit balanced end tags rather than
HTML optional-end-tag shorthand so the server can validate that boundary before
advertising `r: 1`. Components omitted by a successful parent render remain
pending through the official `cids_will_destroy`/`cids_destroyed` handshake.
Rendering the identity before final confirmation revives the same instance, CID,
and state; final confirmation disconnects and forgets only components still
absent. HTTP-only components, nested ones included, are disconnected after the
response is built.

### 3.4 Streams

`LiveView.stream_insert(container_id, item_id, rendered, at=-1, limit=None)`,
`stream_delete`, and `stream_reset` queue browser-owned collection mutations.
`stream_contents(container_id)` replays the queue into trusted HTML for the
disconnected response and becomes a Phoenix keyed stream comprehension for a
connected render.

A stream container has a unique DOM `id` and `phx-update="stream"`. Each inserted
item has one explicitly balanced root element whose DOM `id` matches the item
ID. Container and item IDs cannot contain ASCII whitespace or control
characters, and duplicate root `id` attributes are rejected. New items append at
`-1` or insert at the requested non-negative index.
Positive limits retain the first N children and negative limits retain the last
N. Inserting an existing ID updates it without changing position.

The wire tuple is:

```text
[ref, [[item_id, at, limit, update_only], ...], [delete_id, ...]]
[ref, inserts, delete_ids, true]  # reset
```

The fourth element is omitted unless reset is requested. Sending `false` would
still mean reset because the official client tests tuple-element presence.
Operations are connection-local, consumed once by the next successful render,
discarded after rejected events, and cleared on disconnect.

### 3.5 Server-initiated updates

Timers, subscriptions, and other page-owned background tasks call `send_info`
instead of mutating connected page state directly. The method immediately
returns `False` before connection, after disconnect, or when its bounded
32-message queue is full. Accepted messages execute `handle_info` on the same
connection task that processes Phoenix Channel events, renders, component and
stream operations, and outbound WebSocket writes. A successful callback sends:

```text
[join_ref, null, topic, "diff", tree]
```

The default `handle_info` raises `UnknownInfoError`. Any unhandled info failure
is a server failure and closes the connection with code `1011`. The page must
stop and await its background tasks from `disconnect`; reconnect creates a fresh
page instance and queue. Info traffic does not extend the browser's inbound idle
deadline.

### 3.6 Client hooks, pushed events, replies, and component updates

The bootstrap passes `globalThis.ToriLiveHooks`, created as an empty object when
absent, as the official `hooks` option of `LiveSocket`. The client keeps that
object by reference, so application scripts register hooks by assigning
properties on it before hooked elements mount; a script placed before the
deferred client script in `render_document` always runs first. Elements use
`phx-hook="Name"` with a unique DOM `id`. The official runtime's `Phoenix.*`
built-in hooks and runtime hooks (`<script data-phx-runtime-hook="Name">` with
`window.phx_hook_Name`) resolve unchanged. ToriPy adds no hook runtime and does
not inspect hook code; hook scripts are trusted application code.

`this.pushEvent` and `pushEventTo` in a hook send ordinary `event` messages
with `type: "hook"`. They dispatch to page or component `handle_event` like any
other browser event.

`push_event(event, payload=None, dispatch="after")` validates a non-empty event
name and a mapping payload with string keys that encodes as a JSON object with
finite numbers, snapshots it, and queues it on the page. Components queue
through their owning page. The next render sent to the browser carries the
queue under the top-level `e` key of the join `rendered` tree, the event or live
patch reply `diff`, or the info `diff` push:

```text
e: [[event, payload], [event, payload, true], ...]
```

The trailing `true` marks `dispatch="before"`, which the official client
dispatches before applying the diff; other events dispatch after it. Each event
becomes a `phx:<event>` window event, which hooks receive through
`handleEvent`. Pushed events are discarded with rejected events, when the
handler navigates away with `push_navigate` or `redirect` (a patch keeps them),
after the disconnected HTTP render, and on disconnect.

A page or component `handle_event` that returns a mapping replies to the
browser event. The reply follows the `push_event` payload rules and becomes the
top-level `r` key of that event's reply `diff`; the official client resolves the
`pushEvent` reply callback or promise with it. `None` sends no reply. A handler
that navigates away drops its reply, and an invalid reply is an application
failure that closes the connection with `1011`.

`send_update(component_type, component_id, assigns=None)` queues an update for
the component identity `(component_type, component_id)`. Before the next render,
queued updates call `update(assigns)` in call order on components rendered by
the previous render; updates for other identities are dropped. Assigns passed
to `live_component` during that render are applied afterwards. Queued updates
are discarded with rejected events, after the disconnected HTTP render, and on
disconnect. Background tasks still deliver work through `send_info`.

### 3.7 Flash

`put_flash(kind, message)` stores a string message under a non-empty string
kind, `clear_flash(kind=None)` removes one kind or all, and the read-only
`flash` mapping is rendered by the page like any other state. The page layout
is the application's `render`, so flash markup belongs there. The official
client's `lv:clear-flash` event, usually sent with `phx-value-key`, is handled
by the server before page or component handlers: a `key` value clears that kind
and anything else clears all flash.

Flash travels with navigation the way Phoenix carries it. A navigation queued
by an event, live patch, info, or async handler carries only the flash put
since the last render, so messages the page already showed stay behind. A
navigation queued while mounting, by on-mount hooks, `mount`, or the mount's
`handle_params` over HTTP or on a join, carries the page's whole flash, because
the page was never shown; flash received from the previous page therefore
passes through a page that immediately moves on, unless that page clears it.
The flash travels as follows:

- `push_navigate` adds a signed flash token as `flash` to the `live_redirect`
  reply, push, or join error. The client sends it back in the next join's
  `flash` field, which seeds the new page's flash before `mount`.
- `redirect` adds the token to the `redirect` payload. The official client
  stores it in the `__phoenix_flash__` cookie for 60 seconds before loading the
  target. A page HTTP request with that cookie verifies it, seeds the flash, and
  answers with a `Set-Cookie` that deletes it. A redirect from the disconnected
  mount sets that cookie directly on its `302`. Flash never follows a redirect
  to another host, such as one in `redirect_hosts`, because no page there would
  consume the cookie before a later visit showed it. The cookies the server
  writes are not `HttpOnly`, so the client's `document.cookie` writes can still
  replace them.
- The disconnected render's flash is signed into the mount token and seeds only
  the first connected mount of that document (`_mounts` is `0` and the join is
  not a live navigation), so reconnects do not repeat it.

Flash tokens are HMAC-SHA256 signed with the LiveView secret under a separate
purpose from mount tokens, expire after 60 seconds like Phoenix flash, and are
ignored when invalid or expired. Flash put by a rejected event stays on the page
like any other state change but does not travel with a later navigation.

### 3.8 Async work

`start_async(name, function)` awaits `function()` in its own task and delivers
the outcome to `handle_async(name, result)` on the connection task, serialized
with events and `handle_info`, followed by an unreferenced `diff` push. The
result is an `AsyncResult` with `ok` and `result`, or `failed` holding the
exception; a function that does not return an awaitable fails with
`TypeError`. Only a connected page starts work; the disconnected render ignores
the call. Starting a name that is still running cancels the previous task and
drops its result.

`assign_async(name, function, reset=False)` mirrors Phoenix `assign_async`. It
sets the public attribute `name` to an `AsyncResult` with `loading` true,
keeping a previous `result` and `ok` unless `reset` is true, and settles it to
ok or failed without calling `handle_async`. The disconnected render therefore
shows the loading state. `name` must be a public identifier that is not a class
attribute of the page or component, so a method, property, or class variable
such as `title`, `flash`, or a component's `id` cannot be replaced; a
class-level `AsyncResult` default is allowed.

`cancel_async(name)` cancels running work and returns whether the name had
work pending. A cancelled task's outcome arrives with `failed` set to
`asyncio.CancelledError`; work that already finished delivers its real outcome.
Async completions share the connection's server queue with `send_info` but do
not count against its 32-message bound, because each task delivers at most
once. Failed work is logged as a warning. A raising `handle_async` is a server
failure that closes the connection with `1011`. Disconnect and live navigation
cancel every task of the outgoing page, and removing a component cancels the
component's tasks before its `disconnect` hook runs. Cancellation in Python is
cooperative, so the server waits for cancelled tasks only up to
`LiveViewOptions.async_cancel_timeout_seconds` (5 seconds by default) and then
logs a warning naming the tasks that ignored cancellation. Those tasks keep
running detached, but their results are never delivered.

### 3.9 Dynamic module

`LiveViewModule.for_root(options, pages, embedded=(), imports=(), key="default")`
returns a ToriPy `DeferredModule`. It accepts explicit
`LiveSession(name, on_mount)`
values grouping routes into navigate boundaries with shared mount hooks.
Pages without a session belong to one unnamed default session. Materialization
creates:

- one ordinary HTTP controller route per explicit page path;
- one JavaScript asset route containing the two official clients and a minimal
  ToriPy bootstrap;
- one native WebSocket gateway at `<socket_path>/websocket`;
- one request-scoped provider per page;
- immutable options and page registry values.

On-mount hooks run before `mount` on both HTTP and Channel joins. Authorization
belongs in hooks, `mount`, and `handle_params`: live navigate rejoins on the
existing socket and never passes the HTTP pipeline again. Navigating across
sessions always falls back to a full page reload.

The configured `socket_path` is the Phoenix endpoint base. Phoenix Socket adds
`/websocket?vsn=2.0.0`. Page paths must not conflict with the endpoint base,
transport route, or asset path. Module keys distinguish independent
materializations.

`embedded=` lists pages rendered only as child LiveViews. They get a
request-scoped provider but no path, and must not declare `@live_view`; a routed
page may also be a child.

### 3.10 Child LiveViews

`LiveView.live_render(page_type, view_id, params=None)` may only run while the
page renders. It places a child LiveView: a registered page that mounts with
`params` (strings) as `MountContext.params` and the page's resource, and then
renders, handles events, receives info and async results, and updates as its
own view. `view_id` becomes the container's DOM id and the `lv:<view_id>`
channel topic; it is 1 to 128 letters, digits, `_`, or `-`, not
`tori-live-root`, and unique on the page.

The container is `<div id data-phx-session data-phx-static="" data-phx-parent-id>`
with the rendering view's id as parent. Its session is a child token with its
own HMAC purpose, binding the child page, view id, parent view, params, and the
page's resource and live session. A page keeps the token for a view id while
its type and params stay the same, so an unchanged container stays out of
diffs. The HTTP render mounts each child disconnected in its own work scope,
renders its children in turn up to eight levels deep, and places the HTML in the
container; a child may not navigate there. The connected tree carries the empty
container, and the official client keeps a joined child's container and
contents when its parent patches.

Children do not run the live session's on-mount hooks or `handle_params`, as in
Phoenix: a child authorizes in its own `mount`. Only the main view may
`push_patch`; a child that calls it raises `LiveViewError`. A child's
`push_navigate` replies `live_redirect` on its own topic and closes the child,
and the client then replaces the main view; `redirect` replies `redirect`.
A child's title travels only when it returns one. Sticky children that survive
navigation, container tag and attribute options, rendering a child from a
component, and isolating one child's failure from the connection are not
implemented.

## 4. Browser Assets

The package vendors unchanged official global minified builds:

```text
phoenix@1.8.13
SHA-256: b8702c214c5c7f2c476d827a22b5f337818ab7cb50d48b066a7a8c9691e8b923

phoenix_live_view@1.2.11
SHA-256: 04163ddbfc277452590a7a391c806e1c71883522b106e508b7a9da514c6c3b12
```

`static/phoenix_assets.lock.json` records package versions, artifact paths,
source URLs, filenames, and checksums. `scripts/sync_phoenix_assets.py` verifies
all downloads before writing either file. The wheel contains the verified bytes;
serving or importing the package performs no network request. Minified assets
are Git binary files so checkout line-ending conversion cannot change hashes.

The served client concatenates Phoenix, Phoenix LiveView, and a small bootstrap
that creates `LiveView.LiveSocket` with `Phoenix.Socket`, the
`globalThis.ToriLiveHooks` hooks object (created as an empty object when
absent), and a params function, connects it, and publishes the instance as
`globalThis.liveSocket`. The official runtime hands the same params option to
`Phoenix.Socket`, which serializes it into the WebSocket URL on every
connection, and LiveView writes its join fields (`_mounts`, `_mount_attempts`,
`_track_static`, `_live_referer`) into the object it receives. The params
function therefore returns a fresh shallow copy of `globalThis.ToriLiveParams`,
an object or a function of the root element read at each call, so join fields
never reach the WebSocket URL. Application params do appear in that URL, as in
Phoenix, so they must not carry secrets. This bootstrap does not fork or
reinterpret the official browser runtime.

## 5. HTTP Lifecycle

For a page request, the generated controller:

1. Builds the resource from the request path and raw query. A valid
   `__phoenix_reload_status__` cookie signed for this page and resource answers
   with its client error status and deletes the cookie, without mounting.
2. Resolves the request-scoped page provider from `HttpContext`.
3. Seeds the flash from a valid `__phoenix_flash__` cookie.
4. Calls `mount` with `connected=False`.
5. Renders the page, components, and disconnected stream contents once, and
   mounts and renders each child LiveView into its container.
6. Signs page identity, path params, resource, flash, and issue time.
7. Builds `#tori-live-root` with `data-phx-main`, `data-phx-session`, an empty
   `data-phx-static`, and the ToriPy endpoint-base attribute.
8. Passes the root and deferred client script to `render_document`.
9. Disconnects HTTP-only components and clears stream operations.
10. Returns UTF-8 HTML with `Cache-Control: no-store`, deleting a received flash
    cookie.

An `HttpException` from the disconnected mount is an ordinary HTTP error
response.

The default document escapes the title. Rendered page HTML and the framework
root/script arguments remain explicit trusted-markup boundaries.

## 6. Rendering Contract

`Rendered` is an immutable pair of static and dynamic tuples. The number of
static fragments is exactly one greater than the number of dynamic fragments.
Pages, components, and stream insertions accept Python 3.14 `Template` values.
`html(template)` converts trusted template statics and escaped interpolations to
`Rendered`; conversions and format specifications apply before escaping.
`fragment(values)` consumes a finite iterable once and composes it positionally.
`classes()` builds an ordinary escaped class string from closed names and
boolean conditions. `attrs()` emits a trusted generated attribute fragment,
omits false or absent values, escapes values, and rejects unsafe names and
executable URL schemes. `rendered(statics, *values)` remains the explicit tuple
form. `raw(value)` is an explicit trust marker and must not wrap untrusted input.

The official client parses a `phx-*` binding value that starts with `[` as a
JSON list of JS commands and runs it. `JS` is the immutable command builder,
mirroring `Phoenix.LiveView.JS` and the `exec_*` handlers of the pinned 1.2.11
client: `push`, `navigate`, `patch`, `dispatch`, `show`, `hide`, `toggle`,
class and attribute changes, `transition`, focus commands, and `exec`. It JSON
encodes arguments when a command is added and validates them at build time:
live hrefs are root-relative, attribute commands follow the `attrs()` rules,
and `exec` targets only `phx-*` command bindings. Interpolation, `attrs()`, and
`rendered()` encode a `JS` value as HTML-escaped JSON and treat it as trusted.
Any other dynamic value that would start a command value or appear inside one
is rejected, except in `phx-value-*`, `phx-target`, `phx-key`, and
`phx-disable-with`, which the client never runs.

Nested `Template`, `Rendered`, component, and stream values remain nested so
they can become Phoenix render subtrees. They must be interpolated without a
conversion or format specification; converting one intentionally turns it into
ordinary text and loses structural semantics. The encoder produces:

```text
normal tree  {s: [statics...], "0": dynamic, ...}
changes      {"2": dynamic, ...}: changed keys only, no s
component    parent dynamic = cid; c[cid] = {s, dynamics, r: 1} or changes
shared       c[cid].s = cid sent in this diff, or -cid the client caches
title        top-level t when it changes; an empty string clears the title
stream       {s, k: {entry indexes, kc}, stream: tuple}, with operations only
events       top-level e: [[event, payload], [event, payload, true], ...]
reply        top-level r: JSON object, in event reply diffs only
```

A join sends the complete render tree. Later renders send only what the
official client's cached tree lacks, following Phoenix fingerprint semantics.
Each join keeps the last page tree it sent, the last tree of every component CID
the client still caches, and the last title:

- A node whose statics are unchanged sends only its changed dynamic keys, and
  the client merges them into the cached node. Unchanged values, nodes,
  components, and titles are left out. A node with new statics, or a value of
  another kind, is sent complete and replaces the cached one.
- New page statics replace the client's whole tree and drop its component
  cache, so every rendered component is then sent complete.
- A component is compared with the last tree sent for its CID, wherever it was
  rendered. A component left out of one render and rendered again before the
  client confirms `cids_destroyed` sends only its changes, because the client
  keeps its tree until that reply. The server forgets a component's tree in the
  reply that lets the client prune it. When only components change, the diff
  holds only `c`, so the client patches those components and leaves the rest
  of the page alone.
- A component sent complete copies its statics from a component sent earlier
  in the same diff (a positive CID) or from a cached component that the same
  render keeps (a negative CID). Its dynamics are sent in full, so they replace
  the copied ones. A cached component the render leaves out never lends its
  statics, because the client may prune it before applying a deferred diff.
- A stream is sent only when the render carries operations. Each render
  consumes them, and the client prunes entries once it applies them.
- An info callback or async result that changes nothing pushes no `diff`; an
  event reply then carries an empty diff.

The local `fingerprint` and `diff` helpers remain available for comparing
`Rendered` values but do not drive the wire protocol. Lists built with
`fragment()` are plain trees, so a change in their length sends the whole list
again; Phoenix keyed comprehensions are used only for streams.

Template interpolation is safe for HTML text and quoted attribute values. It is
not context-aware and must not supply tag names, attribute names, unquoted
attributes, CSS, or JavaScript. Template statics, direct `str` render returns,
`raw()`, and mappings passed to `attrs()` remain application-controlled trust
boundaries.

## 7. Mount Tokens

Mount tokens use compact JSON, URL-safe Base64 without padding, and an
HMAC-SHA256 hex signature. Payload fields are page identity, route action,
session name, path params, resource, the disconnected render's flash when
present, and issue time. Verification uses constant-time signature comparison,
requires string params and flash, rejects excessive clock skew, and enforces a
finite age. Flash tokens and reload tokens use the same encoding with distinct
HMAC purposes, so no kind verifies as another. A reload token carries page
identity, resource, a 4xx status, and issue time, and expires after 60 seconds.

Tokens provide integrity and expiry, not confidentiality, authentication,
authorization, replay prevention, or durable session storage. Applications own
authorization. Replicas serving one application need the same secret.

## 8. Phoenix Channels Lifecycle

Before acceptance, the gateway validates Origin. It then:

1. Accepts the socket.
2. Requires a valid join within `join_timeout_seconds`.
3. Verifies the mount token and resolves the registered page provider.
 4. Seeds the flash, attaches the info queue, and calls `mount` with
    `connected=True` and the join params, then `handle_params` with the join
    URL params. An `HttpException` with a 4xx status from on-mount hooks,
    `mount`, `handle_params` (including for a `push_patch` the mount queued), or
    the join render disconnects the page and answers the join with
    `{reason: "reload", status, token}`. The official client stores the token
    in the `__phoenix_reload_status__` cookie for 60 seconds and reloads the
    document; that HTTP request answers with the same status, so the HTTP
    pipeline renders the error even when the disconnected mount would succeed,
    and the browser cannot reload in a loop.
 5. Sends the complete Phoenix join render tree and starts the client's render
    state afresh.
 6. Waits concurrently for inbound frames, accepted info messages, and finished
    async work.
 7. Processes one event, heartbeat, component-destruction message, live patch,
    info callback, or async result at a time.
 8. Sends referenced `phx_reply` event diffs or unreferenced server `diff`
    pushes, each carrying only changes. A queued `push_patch` adds an
    unreferenced `live_patch` push;
    `push_navigate` replies `live_redirect` and the client rejoins on the same
    socket; `redirect` replies `redirect` for a full page reload.
 9. Detaches the info queue, disconnects all remaining components, and calls page
    `disconnect` exactly once when a connected page session ends. Live navigate
    disconnects the outgoing page and mounts the new page on a fresh join.

While the main view is joined, the client joins each child container on its own
`lv:<view_id>` topic over the same socket. A child join carries the child token
as `session`, connect `params`, and an optional `flash` token, but no URL. It is
answered only when the token verifies, names this topic, carries the main
view's live session, and names a parent joined on this connection; otherwise the
reply is `{reason: "unauthorized"}`. A second join of a joined topic closes with
`1002`. A joined child has its own work scope, page instance, render state,
info queue, and join ref; the gateway serializes its events, component
messages, info callbacks, and async results with the main view's on the
connection task and replies and pushes on the child's topic. A 4xx
`HttpException` during a child's connected mount answers its join with a
`reload` token for the main page and resource, and navigation while mounting
answers with `live_redirect` or `redirect`.

A child's `phx_leave` closes it after its own children. Closing any view,
including the main view on leave, navigation, or disconnect, closes its children
first. A message for a child topic that is not joined receives
`{status: "error", response: {reason: "unmatched topic"}}`, as from Phoenix, and
its `phx_leave` an empty successful reply. Application failures in a child close
the connection with `1011`, like failures in the main view.

Reconnect creates a new connection scope and page instance and repeats a full
snapshot join. The server does not retain disconnected page instances.

All text frames use the Phoenix V2 five-element array:

```text
[join_ref, ref, topic, event, payload]
```

The root topic is `lv:tori-live-root`. The initial event is `phx_join` with
equal non-null string `join_ref` and `ref`; its payload carries the mount token
as `session`, an optional `params` object, and an optional `flash` token string.
Other `params` or `flash` types close with `1002`. A successful `phx_reply` has:

```text
{status: "ok", response: {rendered: tree, liveview_version: "1.2.11"}}
```

Browser events use event name `event` and payload fields `type`, `event`,
`value`, and optional numeric `cid`. Client patch links send `live_patch` with
the full URL; same-page targets run `handle_params` and reply a diff, while
other targets reply `link_redirect` so the client rejoins. Form values use Phoenix-compatible bracket
and list decoding, and their metadata is merged before application dispatch.
Successful events receive `{status: "ok", response: {diff: tree}}`; the tree
carries pushed events under `e` and a handler reply under `r`. Hook events use
`type: "hook"` and follow the same path. Unknown
events and CIDs receive successful no-render replies carrying a reason so the
client unlocks the event source. Application exceptions close with `1011`.
Successful info callbacks push `[join_ref, null, topic, "diff", tree]` when the
render changed something; they do not create a second event-version or
stale-retry dialect.

Heartbeats use topic `phoenix`, event `heartbeat`, null `join_ref`, and receive
an empty successful reply with the same ref. `phx_leave` receives an empty
successful reply. Between joins, every `phx_leave` on an `lv:` topic and every
valid heartbeat receives one, because after a join error the official client
leaves that join from its error handler and again when it replaces the view,
and its heartbeat timer keeps running; the idle deadline bounds the wait for the
next join. Before the first join only a join is accepted, within the join
deadline. Reconnect creates a new connection scope and page instance and
performs another full join; the server retains no disconnected page instance and
does not add a second version/stale-event dialect.

## 9. Limits and Close Codes

Inbound UTF-8 byte length is checked before JSON decoding. Binary frames are not
accepted. Join and idle waits are finite.

```text
1001 idle deadline or reconnectable departure
1002 malformed JSON or invalid Channels/message shape
1003 binary frame where text JSON is required
1008 missing/disallowed Origin or join deadline
1009 inbound frame exceeds max_message_bytes
1011 unexpected mount, render, or handler failure
```

Invalid or expired session tokens receive a Phoenix join error with reason
`unauthorized`. A 4xx `HttpException` anywhere in the connected join, from
on-mount hooks through the join render, receives a join error with reason
`reload`, its status, and a reload token. Client disconnect frames end the
loop without another close.
Cancellation is re-raised so application shutdown remains cooperative.

## 10. Origin and Deployment Security

Allowed origins are normalized absolute `http` or `https` origins with explicit
effective ports and no credentials, path, query, or fragment. With no explicit
list, the gateway requires the Origin corresponding to the WebSocket scheme and
Host header. Missing or malformed origins fail closed.

Deployments behind proxies must make Host and scheme trustworthy or configure an
explicit allowlist. Production uses TLS. Message limits, deadlines, and token
expiry are abuse controls, not substitutes for rate limiting or authorization.

## 11. Deliberate Non-Goals

The package does not implement upload transport, sticky child LiveViews,
durable sessions, cross-replica session migration, durable or
supervised background jobs, or `stream_async`. The LiveView integration requires the Starlette
adapter; the native ASGI adapter serves no WebSocket scopes.

## 12. Acceptance

Acceptance requires package tests for rendering, token integrity/expiry,
declaration validation, HTTP root output, exact asset hashes, Channels joins and
replies, form/click events, component CIDs and destruction, heartbeats, reconnect,
title updates, origins, limits, stream ordering/bounds/reset/delete behavior,
serialized server updates, queue bounds, pushed events, event replies, component
updates, flash transfer and clearing, flash and mount token separation, async
results and cancellation, connect params, reload join errors, changed-only diffs
checked against a port of the pinned client's merge over random render
sequences, deadlines, close codes, and cleanup. The pytest-bdd Playwright
scenarios must exercise the real vendored official clients, including a hook
that pushes an event, receives its reply, and handles a pushed server event;
flash dismissal and transfer across `push_navigate` and `redirect`; an
`assign_async` loading state; connect params with `_track_static` and
`_live_referer`; a reload after a connected-mount client error;
changed-only diffs that update one component without touching its sibling,
share cached component statics, bring back a component before its destruction,
and keep stream items across updates that leave the stream out; nested
components that handle their own events and leave with their parent; and
child LiveViews that join under their parent, handle their own events, end when
removed, and navigate the page. Package tests cover child tokens, HTTP child
rendering, child joins under joined parents, child info, leaves, navigation,
reload, and titles. Ruff,
formatting, ty, wheel/sdist build, artifact verification, and isolated import
smoke run through `uv`.
