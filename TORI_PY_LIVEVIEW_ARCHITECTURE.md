# ToriPy LiveView Architecture

## 1. Purpose

`tori-py-liveview` provides server-rendered interactive pages for ToriPy. It is
a clean-room Python server implementation of the public behavior exposed by
Opal LiveView protocol version 2, integrated through ToriPy's public module,
provider, HTTP, and native WebSocket contracts.

The implementation preserves interoperability rather than another language's
internal class graph. The shared browser runtime remains the canonical Opal
JavaScript client. Python owns page lifecycle, event dispatch, rendering,
security limits, and ToriPy dependency injection.

## 2. Package Boundary

```text
tori-py-liveview -> tori-py-framework, starlette
tori-py-framework -X-> tori-py-liveview
```

The integration is separately installable and typed. It must not add LiveView
metadata, discovery, rendering, or protocol behavior to ToriPy core. It may use
Starlette's public request and WebSocket types because this package implements
an ASGI browser transport.

The package must not scan modules, installed distributions, or the filesystem.
Applications explicitly pass page classes to `LiveViewModule.for_root`.

## 3. Public Programming Model

### 3.1 Page declaration

`@live_view(path)` attaches immutable route metadata directly to one
`LiveView` subclass. It performs no global registration. Paths are
root-relative URL paths without authority, query, or fragment components.

`LiveView` exposes:

- `mount(context)` for disconnected and connected initialization;
- `handle_event(event, value)` for connected browser events;
- `render()` returning `Rendered` or trusted static HTML as `str`;
- `title()` returning an optional document title;
- `disconnect()` for connected-session cleanup;
- `render_document(live_root, client_script)` for document customization.

`UnknownEventError` is the expected declaration that an event is unsupported.
Other handler exceptions are server failures and terminate the connection with
close code `1011`.

### 3.2 Mount context

`MountContext` contains the native request or socket, immutable path params,
the signed resource URL, a `connected` flag, and parsed query params.

The HTTP mount receives `connected=False`. A successful WebSocket join receives
`connected=True`. These are distinct page instances; applications must not rely
on in-process object identity to transfer state between them. Signed params and
resource data are the transfer boundary.

### 3.3 Stateful components

`LiveComponent` exposes synchronous `mount`, `update(assigns)`, and `render`
hooks plus asynchronous `handle_event` and `disconnect` hooks. `id` is the
caller-provided stable identity, `myself` is the positive connection-local
target used by `data-opal-target`, and `connected` identifies the HTTP or
WebSocket lifecycle.

`LiveView.live_component(component_type, id, assigns, factory=...)` may only run
inside `render`. Identity is the concrete component type plus `id`. The first
render of an identity constructs and mounts one instance; every render updates
its assigns before rendering. Reusing the identity preserves state, while
rendering it twice in one parent render is an error. The optional factory allows
the parent to pass dependencies it already owns; components are not separately
resolved providers.

An event carrying a component target runs that component's `handle_event` on the
page's serialized connection task. Components omitted by a successful parent
render are disconnected and forgotten. Recreating the identity produces fresh
state and a new target. HTTP render components are disconnected after the
response is built, and all connected components are disconnected before their
parent page. Nested components are not supported.

### 3.4 Streams

`LiveView.stream_insert(container_id, item_id, rendered, at=-1, limit=None)`,
`stream_delete`, and `stream_reset` queue ordered browser-owned collection
mutations. `stream_contents(container_id)` replays the current queue into trusted
HTML for the disconnected response. Container and item IDs are non-empty strings,
insertion indexes are `-1` or non-negative safe integers, limits are non-zero
safe integers, and inserted content is `Rendered` or trusted `str` markup.

A stream container has a unique DOM `id` and `data-opal-stream`. Each inserted
item has exactly one root element whose DOM `id` matches the declared item ID;
the unchanged browser client validates this before applying any operation in the
batch. Normal structural morphing preserves stream-container children. Only
stream operations own their insertion, update, deletion, reset, order, and
bounds.

Inserting an existing ID morphs it in place without changing position. New
items append at `-1` or insert at the requested non-negative child index. A
positive limit retains the first N children and a negative limit retains the
last N. Operations are connection-local, consumed once by the next render
message, cleared after rejected events, and cleared on disconnect.

### 3.5 Dynamic module

`LiveViewModule.for_root(options, pages, imports=(), key="default")` returns a
ToriPy `DeferredModule`. Materialization creates:

- one ordinary HTTP controller route per explicit page;
- one ordinary JavaScript asset route;
- one native WebSocket gateway;
- one request-scoped provider per page;
- immutable options and page registry values.

Imported modules allow page constructor dependencies to be resolved through the
normal module graph. Page routes participate in normal ToriPy HTTP execution.
The WebSocket page resolves from the connection scope owned by the gateway.

Page paths must be unique and must not conflict with the socket or asset path.
Module keys distinguish multiple independent materializations.

## 4. Browser Asset

The client is vendored unchanged from:

```text
repository: https://github.com/mikeoz32/opal
commit: e492477d62bbe578eb6a7b132db60e5b845ceb35
path: assets/opal_live_view.js
SHA-256: abd50912b09bbfdfc849462d66559de57a706eb63651b08e3d412738becd5653
```

`static/opal_live_view.lock.json` is the machine-readable pin. The sync script
downloads that exact path and refuses checksum drift before writing. The wheel
contains the verified bytes, and serving or importing the package performs no
network request.

The client keeps the Opal names `OpalLiveView`, `connectAll`, `data-opal-*`, and
`opal:*`. ToriPy-specific endpoint defaults are `/_tori/live` and
`/_tori/live.js`; they do not define a separate wire dialect.

## 5. HTTP Lifecycle

For a page request, the generated controller:

1. Resolves the request-scoped page provider from `HttpContext`.
2. Builds the resource from the request path and raw query.
3. Calls `mount` with `connected=False`.
4. Renders the page, declared component identities, and disconnected stream
   contents once.
5. Signs page identity, path params, resource, and issue time.
6. Builds a root carrying `data-opal-live-root`, token, and socket path.
7. Passes the root and module script to `render_document`.
8. Disconnects the HTTP-only components and clears queued stream operations.
9. Returns UTF-8 HTML with `Cache-Control: no-store`.

The default document escapes the title. Rendered page HTML and the framework
root/script arguments remain explicit trusted markup boundaries.

## 6. Rendering Contract

`Rendered` is an immutable pair of static and dynamic tuples. The number of
static fragments is exactly one greater than the number of dynamic fragments.

The fingerprint is SHA-256 over compact UTF-8 JSON encoding of the static
tuple. Equal fingerprints therefore mean equal static structure. A diff between
equal structures maps changed zero-based dynamic indexes to replacement strings.
Different structures require a full snapshot.

`rendered(statics, *values)` escapes dynamic values with HTML escaping. Nested
component `Rendered` values are flattened into parent dynamic positions, which
lets each component update independently when the parent fingerprint remains
stable. `raw(value)` is an explicit trust marker and must never be applied to
untrusted input.

`stream_contents` is the corresponding trusted boundary for markup already
queued through stream operations. Connected renders normally produce an empty
stream-container dynamic after the previous batch is consumed; the browser
preserves existing children and applies the separately validated operations.

## 7. Mount Tokens

Mount tokens use compact JSON, URL-safe Base64 without padding, and an
HMAC-SHA256 hex signature. Payload fields are page identity, path params,
resource, and issue time. Verification uses constant-time signature comparison,
requires string params, rejects excessive clock skew, and enforces a finite
maximum age.

Tokens provide integrity and expiry, not confidentiality, authentication,
authorization, replay prevention, or durable session storage. Applications must
perform user authorization in their own providers and lifecycle hooks. All
replicas serving one application need the same secret.

## 8. WebSocket Lifecycle

Before acceptance, the gateway validates Origin. It then:

1. Accepts the socket.
2. Requires a valid join within `join_timeout_seconds`.
3. Verifies the mount token and resolves the registered page provider.
4. Calls `mount` with `connected=True`.
5. Sends version `0` as a full render snapshot plus any queued stream operations.
6. Processes one inbound event or heartbeat at a time.
7. Disconnects removed components after each successful render.
8. Disconnects all remaining components and calls page `disconnect` exactly
   once when a connected page session ends.

Reconnect creates a new connection scope and page instance and repeats a full
snapshot join. The server does not retain disconnected page instances.

## 9. Protocol Version 2

All frames are text JSON objects.

Client messages:

```text
join      {type, protocol: 2, token}
event     {type, event, value, target, version, ref}
heartbeat {type, ref}
```

`version` is a non-negative integer. Event and heartbeat `ref` values are
positive integers. `target` is null for the page or a positive component ID.

Server messages:

```text
full render {type: "render", protocol: 2, version, rendered, streams?, title?}
diff render {type: "render", protocol: 2, version, fingerprint, diff,
             streams?, ref?, status?, title?}
heartbeat   {type: "heartbeat", ref}
error       {type: "error", reason, ref}
```

`rendered` contains `fingerprint`, `statics`, and `dynamics`. `diff` uses JSON
string keys for dynamic indexes. An absent title leaves `document.title`
unchanged; null is not sent as an instruction.

`streams`, when present, is a non-empty ordered array using the canonical Opal
operation shapes:

```text
insert {op: "insert", container, id, html, at, limit?}
delete {op: "delete", container, id}
reset  {op: "reset", container}
```

The server omits the field for an empty queue. The client validates the complete
array, stream containers, insertion values, single-root item markup, and item-ID
match before mutating the DOM, so an invalid operation leaves the batch
unapplied.

The browser allows one event in flight. A matching-version page event executes,
increments the version, and produces a diff or snapshot with the same `ref`.
An event with a stale version does not execute; the server returns the current
render state with `status="stale"` and the event ref so the client can retry.

A known non-null component target dispatches to that component. An unknown
target returns `reason="unknown_target"`; unsupported page or component events
return `reason="unknown_event"`. Neither error advances the version.

## 10. Limits and Close Codes

Inbound byte length is checked before JSON decoding. Binary frames are not
accepted. Join and idle waits are finite.

```text
1001 idle deadline or normal reconnectable departure
1002 malformed JSON, unsupported protocol, or invalid message shape
1003 binary frame where text JSON is required
1008 missing/disallowed Origin, join deadline, invalid/expired token, unknown page
1009 inbound frame exceeds max_message_bytes
1011 unexpected server, mount, render, or handler failure
```

Client disconnect frames end the loop without sending another close frame.
Cancellation is re-raised so application shutdown remains cooperative.

## 11. Origin and Deployment Security

Allowed origins are normalized absolute `http` or `https` origins with explicit
effective ports and no credentials, path, query, or fragment. If no list is
configured, the gateway requires the Origin corresponding to the WebSocket
scheme and Host header. Missing or malformed origins fail closed.

Deployments behind proxies must ensure Host and scheme are trustworthy or set an
explicit allowlist. Production uses TLS. Message limits, deadlines, and token
expiry are abuse controls, not substitutes for rate limiting or authorization.

## 12. Deliberate Non-Goals

The package does not implement nested components, upload transport,
server-initiated `send_info`, durable sessions, cross-replica session migration,
background event delivery, or JavaScript hooks.

## 13. Acceptance

Acceptance requires package tests for rendering, token integrity/expiry,
declaration validation, HTTP output, exact client bytes, joins, diffs, stale
resynchronization, component identity/state/target routing, errors, origins, size
limits, stream ordering/bounds/reset/delete semantics, atomic browser validation,
deadlines, close codes, and cleanup. Ruff, formatting, ty, wheel/sdist build,
artifact content verification, and isolated import smoke must pass through `uv`.
