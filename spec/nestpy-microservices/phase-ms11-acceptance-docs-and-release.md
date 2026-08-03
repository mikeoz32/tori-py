# MS11: Acceptance, Documentation, and Release

## Purpose

Prove the package from built artifacts, document operational semantics, and
complete independent review before release.

## Examples

- Standalone RPC service with several controllers and simple `@rpc` methods.
- Three replicas sharing one wildcard-bound service queue.
- `ServiceCluster` client calling several logical services through one reply
  listener.
- Hybrid Starlette HTTP plus RPC/events application.
- `SERVICE_POOL`, `SINGLETON`, ephemeral broadcast, and reliable broadcast.
- Deadline-bound backlog while every service replica is offline.
- Explicit idempotent mutating RPC example.
- Outbox relay boundary example that does not claim built-in outbox support.

## Documentation

- Installation with and without `[rabbitmq]`.
- Service identity and one-service-per-application rule.
- Controller discovery and decorator API.
- Exact RabbitMQ exchange/queue/binding/routing topology.
- Competing-consumer balancing and non-strict round-robin caveat.
- RPC deadlines, timeout, cancellation, duplicate execution, and idempotency.
- Shared reply queue, late replies, reconnect, and outcome uncertainty.
- Event delivery modes, reliable subscriptions, and broadcast identity.
- Publisher confirms versus consumer acknowledgements.
- Delivery limits, delayed retry, DLX, quarantine, and replay operations.
- Lifecycle, readiness, shutdown, metrics, security, and RabbitMQ permissions.
- Testing with in-memory and real RabbitMQ transports.
- Boundaries from CQRS, event sourcing, SQLAlchemy, outbox/inbox, and Kinker
  service extraction.

## Artifact Gates

- Build wheel and sdist with uv.
- Inspect exact file inventories.
- Install base artifact into an isolated environment and import without
  `aio-pika`.
- Install `[rabbitmq]` artifact and run a real broker smoke service/client.
- Verify `py.typed`, package metadata, extras, and public facades.
- Verify no source-worktree imports mask missing artifact files.

## Quality Commands

- Package-focused pytest through uv.
- Repository-wide pytest through uv.
- `uv run ruff check .`.
- `uv run ruff format --check .`.
- `uv run ty check` with the new package source/tests and all existing paths.
- Documentation/link verification through uv.
- Artifact verification scripts through uv.

## Independent Review

Review axes:

- architecture and package boundaries;
- RabbitMQ topology and balancing correctness;
- asyncio task/resource ownership;
- deadlines, cancellation, and shutdown;
- request/reply correlation races;
- ACK, confirm, redelivery, and indeterminate outcomes;
- event delivery cardinality and durable queue identity;
- wire compatibility and schema evolution;
- security, privacy, and safe observability;
- public API, typing, docs, and artifact completeness.

All correctness, reliability, security, and missing-test findings must be
resolved or explicitly accepted in the governing architecture before release.

## Final Acceptance Matrix

- Multi-controller automatic discovery without endpoint modules.
- One service root and deterministic duplicate diagnostics.
- One RPC queue and one wildcard binding per logical service.
- Two/three replica competing-consumer behavior.
- Service-wide prefetch/concurrency and saturated replica behavior.
- Unknown service/method/version/schema distinctions.
- Deadline-bound offline backlog.
- Response-confirm-before-request-ACK ordering.
- Duplicate execution/reply and idempotency guidance.
- Shared cluster reply listener and reconnect behavior.
- All event modes and reliable/unreliable delivery.
- Scope cleanup before settlement.
- Startup rollback and bounded graceful/forced shutdown.
- Standalone and hybrid hosting.
- Lazy optional imports and isolated artifacts.
- Full quality suite and independent review.

## Exit Criteria

- Every governing architecture acceptance criterion has a passing executable
  test or artifact check.
- Documentation does not overstate exactly-once, strict round-robin, live
  membership, durability, or transactional publication.
- The package is releasable without changes to Nestpy core dependencies.
