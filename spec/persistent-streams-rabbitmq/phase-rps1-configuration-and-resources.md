# RPS1: Configuration and Resources

Status: incomplete after lifecycle and reconnect guarantee revision.

## Entry Gate

The currently required pinned-driver checks pass; RPS0 remains incomplete.

## Requirements

- Immutable bounded redacted connection, TLS, reconnect, declaration, confirm,
  credit, queue, byte, timeout, router, and start-capability options.
- Sync and annotation-driven async adapter modules exporting the canonical
  `StreamAdapterFactory` token and explicitly imported by the single always-global
  Nestpy root.
- Owned locator, metadata, producer, consumer, callback, and recovery resources;
  reverse-order rollback and idempotent bounded close.
- Explicit unnamed producer mode and optional named-producer coordinate provider.
- One base producer for unnamed publications with physical stream count bounded by
  validated `max_streams`; lifetime-stable coordinate slots and all additional
  named producers are bounded by `max_named_producers`.
- Provider construction performs no I/O; startup publishes exact capabilities
  before topology or intake.

## Exit Criteria

Resources start, fail, and close deterministically without declaration,
publication, subscription, or user callbacks.
