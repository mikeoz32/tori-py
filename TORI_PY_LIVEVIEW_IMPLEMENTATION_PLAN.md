# ToriPy LiveView Implementation Plan

## LV0: Package and Contracts

- Add the independently installable typed package and workspace registration.
- Record the clean-room architecture and public facade.
- Pin and verify the canonical Opal protocol-v2 browser asset.

## LV1: Page Runtime

- Add explicit page metadata, request-scoped providers, mount context, lifecycle,
  safe dynamic rendering, fingerprints, and structural diffs.
- Generate normal HTTP routes and complete initial documents.

## LV2: Protocol Runtime

- Add signed mount tokens and one native WebSocket gateway.
- Implement join, event, stale resynchronization, heartbeat, title, reconnect,
  protocol validation, finite deadlines, Origin checks, and close semantics.

## LV3: Acceptance

- Add the counter example, package guide, exact asset tests, security/edge tests,
  build verification, type checks, formatting, and family release integration.

## LV4: Stateful Components

- Add connection-local component identity, mount/update/render/event lifecycle,
  removal and disconnect cleanup, and explicitly targeted protocol-v2 events.
- Exercise isolated component state through server protocol tests and the exact
  pinned browser client.

## LV5: Streams

- Add ordered insert/update/delete/reset operation queues, disconnected stream
  contents, bounded prepend/append semantics, and one-shot protocol payloads.
- Exercise retained DOM identity, atomic batch validation, reconnect reset, and
  operation cleanup through the exact pinned browser client.

## LV6: Server-Initiated Updates

- Add a bounded connection-local `send_info` queue and an asynchronous
  `handle_info` callback for timer and subscription messages.
- Serialize info callbacks with browser events, renders, versions, stream
  batches, and outbound writes; reject sends outside the connected lifecycle.

## LV7: Template Authoring

- Map Python 3.14 template strings onto the structural rendering contract while
  preserving escaping, fingerprints, formatting, and trusted composition.
- Accept templates from page and component render hooks and stream insertions;
  retain `rendered` as the lower-level constructor.
- Compose finite template iterables into escaped positional fragments while
  retaining streams for browser-owned collections.
- Compose normalized unconditional and boolean conditional class names without
  bypassing quoted-attribute escaping.

## Deferred

- Evaluate nested components, uploads, navigation, and server hook/reply APIs as
  separate contracts.
