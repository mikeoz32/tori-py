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

## Deferred

- Implement protocol-v2 components and component lifecycle.
- Implement streams without changing their existing browser message shape.
- Evaluate uploads, hooks, and server-initiated messages as separate contracts.
