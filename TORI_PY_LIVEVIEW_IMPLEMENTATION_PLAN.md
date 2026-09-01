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

## Deferred

- Evaluate nested components, uploads, hooks, and server-initiated messages as
  separate contracts.
