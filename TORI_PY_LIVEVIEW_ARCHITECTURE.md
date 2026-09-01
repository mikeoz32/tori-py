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
subclass. `LiveView` exposes:

- `mount(context)` for disconnected and connected initialization;
- `handle_event(event, value)` for connected browser events;
- `render()` returning a Python 3.14 `Template`, `Rendered`, or trusted static
  HTML as `str`;
- `title()` returning an optional document title;
- `disconnect()` for connected-session cleanup;
- `render_document(live_root, client_script)` for document customization.

`UnknownEventError` declares an unsupported event. It produces a successful
no-render Channel reply carrying the reason, so the official client releases
the originating element's loading/lock refs without advancing page state. Other
handler exceptions terminate the connection with close code `1011`.

### 3.2 Mount context

`MountContext` contains the native request or socket, immutable path params, the
signed resource URL, a `connected` flag, and parsed query params.

The HTTP mount receives `connected=False`. A successful Channel join receives
`connected=True`. These mounts use distinct request-scoped page instances.
Signed params and resource data, rather than in-process object identity, are the
transfer boundary.

### 3.3 Stateful components

`LiveComponent` exposes synchronous `mount`, `update(assigns)`, and `render`
hooks plus asynchronous `handle_event` and `disconnect` hooks. `id` is the
caller-provided stable identity. `myself` is the positive connection-local CID
placed in `phx-target`. `connected` identifies the HTTP or WebSocket lifecycle.

`LiveView.live_component(component_type, id, assigns, factory=...)` may only run
inside `render`. Identity is the concrete component type plus `id`. The first
render constructs and mounts one instance; every render updates its assigns
before rendering. Reusing the identity preserves state. Rendering one identity
twice in a parent render is an error.

The encoder places integer CID references in the parent tree and component
trees under the Phoenix `c` map. Component trees carry `r: 1`, allowing the
official client to add `data-phx-component` and `data-phx-view` to their single
root elements. Component markup must use explicit balanced end tags rather than
HTML optional-end-tag shorthand so the server can validate that boundary before
advertising `r: 1`. Components omitted by a successful parent render remain
pending through the official `cids_will_destroy`/`cids_destroyed` handshake.
Rendering the identity before final confirmation revives the same instance, CID,
and state; final confirmation disconnects and forgets only components still
absent. HTTP-only components are disconnected after the response is built.
Nested components are not supported.

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

### 3.5 Dynamic module

`LiveViewModule.for_root(options, pages, imports=(), key="default")` returns a
ToriPy `DeferredModule`. Materialization creates:

- one ordinary HTTP controller route per explicit page;
- one JavaScript asset route containing the two official clients and a minimal
  ToriPy bootstrap;
- one native WebSocket gateway at `<socket_path>/websocket`;
- one request-scoped provider per page;
- immutable options and page registry values.

The configured `socket_path` is the Phoenix endpoint base. Phoenix Socket adds
`/websocket?vsn=2.0.0`. Page paths must not conflict with the endpoint base,
transport route, or asset path. Module keys distinguish independent
materializations.

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
that creates `LiveView.LiveSocket` with `Phoenix.Socket`, connects it, and
publishes the instance as `globalThis.liveSocket`. This bootstrap does not fork
or reinterpret the official browser runtime.

## 5. HTTP Lifecycle

For a page request, the generated controller:

1. Resolves the request-scoped page provider from `HttpContext`.
2. Builds the resource from the request path and raw query.
3. Calls `mount` with `connected=False`.
4. Renders the page, components, and disconnected stream contents once.
5. Signs page identity, path params, resource, and issue time.
6. Builds `#tori-live-root` with `data-phx-main`, `data-phx-session`, an empty
   `data-phx-static`, and the ToriPy endpoint-base attribute.
7. Passes the root and deferred client script to `render_document`.
8. Disconnects HTTP-only components and clears stream operations.
9. Returns UTF-8 HTML with `Cache-Control: no-store`.

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

Nested `Template`, `Rendered`, component, and stream values remain nested so
they can become Phoenix render subtrees. They must be interpolated without a
conversion or format specification; converting one intentionally turns it into
ordinary text and loses structural semantics. The encoder produces:

```text
normal tree  {s: [statics...], "0": dynamic, ...}
component    parent dynamic = cid; c[cid] = {s, dynamics, r: 1}
title        top-level t; an empty string clears a previous title
stream       {s, k: {entry indexes, kc}, stream: tuple}
```

The package currently sends a complete compatible render tree after each
successful event. Phoenix merge semantics still apply in the browser, and
component/stream metadata remains canonical. The local `fingerprint` and `diff`
helpers remain available for comparing `Rendered` values but are not a separate
browser protocol.

Template interpolation is safe for HTML text and quoted attribute values. It is
not context-aware and must not supply tag names, attribute names, unquoted
attributes, CSS, or JavaScript. Template statics, direct `str` render returns,
`raw()`, and mappings passed to `attrs()` remain application-controlled trust
boundaries.

## 7. Mount Tokens

Mount tokens use compact JSON, URL-safe Base64 without padding, and an
HMAC-SHA256 hex signature. Payload fields are page identity, path params,
resource, and issue time. Verification uses constant-time signature comparison,
requires string params, rejects excessive clock skew, and enforces a finite age.

Tokens provide integrity and expiry, not confidentiality, authentication,
authorization, replay prevention, or durable session storage. Applications own
authorization. Replicas serving one application need the same secret.

## 8. Phoenix Channels Lifecycle

All text frames use the Phoenix V2 five-element array:

```text
[join_ref, ref, topic, event, payload]
```

The root topic is `lv:tori-live-root`. The initial event is `phx_join` with
equal non-null string `join_ref` and `ref`; its payload carries the mount token
as `session`. A successful `phx_reply` has:

```text
{status: "ok", response: {rendered: tree, liveview_version: "1.2.11"}}
```

Browser events use event name `event` and payload fields `type`, `event`,
`value`, and optional numeric `cid`. Form values use Phoenix-compatible bracket
and list decoding, and their metadata is merged before application dispatch.
Successful events receive `{status: "ok", response: {diff: tree}}`. Unknown
events and CIDs receive successful no-render replies carrying a reason so the
client unlocks the event source. Application exceptions close with `1011`.

Heartbeats use topic `phoenix`, event `heartbeat`, null `join_ref`, and receive
an empty successful reply with the same ref. `phx_leave` receives an empty
successful reply. Reconnect creates a new connection scope and page instance and
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
`unauthorized`. Client disconnect frames end the loop without another close.
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

The package does not implement nested components, upload channels, live
navigation, server-initiated `send_info`, durable sessions, cross-replica session
migration, background event delivery, or application JavaScript-hook APIs.

## 12. Acceptance

Acceptance requires package tests for rendering, token integrity/expiry,
declaration validation, HTTP root output, exact asset hashes, Channels joins and
replies, form/click events, component CIDs and destruction, heartbeats, reconnect,
title updates, origins, limits, stream ordering/bounds/reset/delete behavior,
deadlines, close codes, and cleanup. The Playwright example must exercise the
real vendored official clients. Ruff, formatting, ty, wheel/sdist build, artifact
verification, and isolated import smoke run through `uv`.
