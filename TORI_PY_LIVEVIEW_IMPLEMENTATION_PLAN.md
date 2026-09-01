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

## Deferred

- Evaluate nested components, uploads, navigation, and application hook/reply
  APIs as separate contracts.
