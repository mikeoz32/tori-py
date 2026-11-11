# ToriPy LiveView Implementation Plan

## LV0: Package and Contracts

- Add the independently installable typed package and workspace registration.
- Record the clean-room architecture and public facade.
- Pin and verify official Phoenix and Phoenix LiveView browser assets.

## LV1: Page Runtime

- Add explicit page metadata, request-scoped providers, mount context, lifecycle,
  safe dynamic rendering, fingerprints, and structural diffs.
- Generate normal HTTP routes and complete initial documents.

## LV2: Protocol Runtime

- Add signed mount tokens and one native WebSocket gateway.
- Implement Phoenix V2 array frames, Channel join/reply/event/heartbeat/leave,
  title updates, reconnect, validation, finite deadlines, Origin checks, and
  close semantics.

## LV3: Acceptance

- Add the counter example, package guide, exact asset tests, security/edge tests,
  build verification, type checks, formatting, and family release integration.

## LV4: Stateful Components

- Add connection-local component identity, mount/update/render/event lifecycle,
  removal and disconnect cleanup, Phoenix CID render trees, explicitly targeted
  events, and the component-destruction handshake.
- Exercise isolated component state through Channels tests and the exact pinned
  official browser clients.

## LV5: Streams

- Add ordered insert/update/delete/reset operation queues, disconnected stream
  contents, bounded prepend/append semantics, and Phoenix keyed stream tuples.
- Exercise retained DOM identity, reconnect reset, and operation cleanup through
  the exact pinned official browser clients.

## LV6: Phoenix Flag-Day Migration

- Remove the Opal protocol-v2 client, object envelopes, `data-opal-*` bindings,
  event versions, and stale-event resynchronization.
- Serve unchanged `phoenix@1.8.13` and `phoenix_live_view@1.2.11` global builds
  with a minimal bootstrap and line-ending-safe checksum custody.
- Move application markup to `phx-*`, the endpoint to `/websocket?vsn=2.0.0`,
  rendering to Phoenix trees, components to CIDs, and streams to official keyed
  comprehensions.
- Verify the contract through package frame tests and Playwright.

## LV7: Template Authoring and UI Prerequisite

- Add Python 3.14 Template rendering plus `html`, `fragment`, `classes`, and
  `attrs` helpers while preserving nested Phoenix render-tree values.
- Accept Templates from pages, stateful components, and stream insertions
  without flattening component CIDs or keyed stream comprehensions.
- Exercise escaping, trusted composition, attribute safety, page/component
  targets, and streams through package and official-client tests.

## LV8: Server-Initiated Updates

- Add a bounded connection-local `send_info` queue and an asynchronous
  `handle_info` callback for timer and subscription messages.
- Serialize info callbacks with Phoenix Channel events, renders, component and
  stream operations, and outbound writes; reject sends outside the connected
  lifecycle and emit successful updates as unreferenced Phoenix `diff` pushes.

## LV9: Hooks, Pushed Events, Replies, and Component Updates

- Pass the `globalThis.ToriLiveHooks` object to the official `LiveSocket`
  `hooks` option so application hooks bind to `phx-hook` elements; route hook
  `pushEvent` messages through the normal event path.
- Add page and component `push_event` with JSON-object payloads and
  before/after dispatch, delivered once under the top-level `e` key of the next
  join, reply, or info render and discarded with rejected events, navigation
  away, the disconnected render, and disconnect.
- Let page and component `handle_event` return a JSON-object reply carried under
  the top-level `r` key of the event reply diff.
- Add page and component `send_update`, applied in order to rendered components
  before the next render and before the parent's `live_component` assigns.
- Exercise frames through package tests and a hook through the exact pinned
  official browser clients.

## LV10: Flash, Async Work, and Join Extras

- Add page and component `put_flash`/`clear_flash` and a read-only `flash`
  mapping, the built-in `lv:clear-flash` event, signed 60-second flash tokens
  on `live_redirect` and `redirect` payloads, join `flash` seeding, the
  `__phoenix_flash__` cookie on the HTTP render and disconnected redirects,
  and first-mount flash from the mount token.
- Add page and component `start_async`, `assign_async`, `cancel_async`, and
  `handle_async` with `AsyncResult`, delivering finished work on the
  connection task and cancelling it with its owner.
- Pass `globalThis.ToriLiveParams` to the official client, expose join params
  as `MountContext.connect_params` with `tracked_static` and
  `static_changed`, and answer a 4xx `HttpException` during the connected
  mount with a `reload` join error.
- Exercise frames through package tests and the browser behavior through
  pytest-bdd scenarios on the exact pinned official clients.

## LV11: Changed-Only Diffs

- Keep the render tree the client caches per join: the last page tree, the last
  tree of every cached component CID, and the last title. A join starts afresh
  and sends the complete tree.
- Send later renders under Phoenix fingerprint rules: unchanged statics send
  only changed dynamic keys, new statics send complete nodes, new page statics
  resend every rendered component, streams travel only with operations, titles
  only when they change, and info or async renders that change nothing push no
  `diff`.
- Compare components with the last tree sent for their CID, forget a tree in
  the `cids_destroyed` reply that lets the client prune it, and send each
  component template's statics once through positive (same diff) or negative
  (cached and kept by the render) CID references.
- Exercise the encoder against a port of the pinned client's merge over random
  render sequences, and the browser behavior through pytest-bdd scenarios on
  the exact pinned official clients.

## LV12: Nested Components

- Add `LiveComponent.live_component`, delegating to the owning page while it
  renders, so components render nested components that share the page's
  identity namespace, CIDs, targets, updates, async work, and destruction
  handshake.
- Exercise nested trees, targeted events, `send_update`, and removal with a
  parent through package tests, random diff sequences, and pytest-bdd scenarios
  on the exact pinned official clients.

## LV13: Child LiveViews

- Add `LiveView.live_render` and `LiveViewModule.for_root(embedded=...)`,
  placing child containers with purpose-separated child tokens bound to the
  child page, view id, parent view, params, resource, and live session, and
  rendering children into their containers over HTTP.
- Join children on their own `lv:<view_id>` topics under a joined parent with
  their own scope, render state, and info queue; serialize them with the main
  view; close descendants first; answer unmatched topics as Phoenix does; and
  keep `push_patch` to the main view.
- Exercise child tokens, HTTP rendering, joins, events, info, leaves,
  navigation, reload, and titles through package tests, and the browser
  behavior through pytest-bdd scenarios on the exact pinned official clients.

## Deferred

- Evaluate uploads, sticky child LiveViews, `stream_async`, and keyed list
  comprehensions as separate contracts.
