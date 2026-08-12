# Nestpy Persistent Streams Implementation Plan

## Status

Implementation status: NPS0-NPS6 complete. The seven stream review findings and
focused NPS7 test, quality, typing, and artifact gates are complete;
repository-wide acceptance remains blocked by unrelated baseline failures
recorded in the verification results.

Architecture:
[`NESTPY_PERSISTENT_STREAMS_ARCHITECTURE.md`](NESTPY_PERSISTENT_STREAMS_ARCHITECTURE.md).

Executable specifications:
[`spec/nestpy-persistent-streams/README.md`](spec/nestpy-persistent-streams/README.md).

## Delivery Principles

1. The framework-neutral persistent-stream contracts remain the governing
   adapter boundary.
2. The application imports one always-global root; that root imports its adapter
   reference internally.
3. Discovery uses public `DiscoveryService` and exact compiled module ownership.
4. Every record attempt receives a fresh Nestpy work scope.
5. Checkpoints advance only after successful scope cleanup.
6. Decode and validation failures stop their physical partition.
7. Stream configuration is immutable and cannot be overridden by publishers.
8. No CQRS, event-handler, or `EventDispatcher` bridge is introduced.
9. Every environment, dependency, test, build, and service command uses `uv`.

## Delivery Order

### NPS0: Workspace and Package Contracts

- Add `packages/nestpy-persistent-streams` to the uv workspace.
- Depend only on `nestpy` and `persistent-streams` at runtime.
- Add `py.typed`, exact public facades, typed diagnostics, and artifact checks.
- Prove imports do not load broker, HTTP, persistence, CQRS, event-sourcing, or
  microservices packages.

Exit gate: isolated base artifacts install, import, and type-check with exact
dependency and facade inventories.

### NPS1: Root Composition and Configuration

- Implement `ConfiguredStreamAdapter` module/token references.
- Implement one always-global `PersistentStreamsModule.for_root()`.
- Implement annotation-driven `for_root_async()` for sync/async factories.
- Internally import the adapter module and reject a second application root.
- Validate immutable bindings and fixed stream/codec/router plus optional named
  producer/ID policy; fully support unnamed publishing.

Exit gate: one root resolves several bindings and one adapter without the app
importing the adapter module separately.

### NPS2: Handler Metadata and Compiler

- Implement independent `@stream_handler` and stream parameter markers.
- Discover every explicit controller through `DiscoveryService`.
- Compile direct methods only with exact `ModuleId` and `ProviderRef`.
- Reject duplicate `(stream, consumer_group)` mappings and invalid signatures.

Exit gate: a multi-module application produces one deterministic immutable
handler registry without package scanning or microservices metadata.

### NPS3: Invocation Pipeline and Checkpoints

- Decode bounded typed DTOs through each binding's codec.
- Execute guards, pipes, interceptors, filters, and handlers in exact-owner work
  scopes.
- Preserve cancellation and cleanup failures.
- Mark completion checkpoint-eligible only after scope finalization succeeds.
- Ensure filters cannot turn any failed attempt into checkpoint eligibility.
- Stop the physical partition on decode, validation, or indeterminate checkpoint
  outcomes.

Exit gate: transport-free tests prove pipeline order, isolation, serial
partition execution, and cleanup-before-checkpoint.

### NPS4: Publishers

- Implement the global raw `StreamPublisher` over configured aliases only.
- Implement named configured publisher tokens.
- Compile explicit async publisher Protocols and register token-backed proxies.
- Route every API through fixed codec, resolver, router, optional producer/ID
  policy, limits, explicit/default UUID handling, and typed publication outcomes.

Exit gate: all publisher forms share one managed runtime and cannot override
binding compatibility policy.

### NPS5: Runtime and Lifecycle

- Prepare adapter topology without intake during singleton startup.
- Query exact checkpoints and reject retention gaps.
- Start partition intake only during application bootstrap.
- Enforce serial per-partition and bounded cross-partition concurrency.
- Fence callback handoff, close admission first, and drain against the shared
  shutdown deadline.

Exit gate: standalone and hybrid fake-adapter applications have deterministic
readiness, rollback, quiescence, and replay-safe forced shutdown.

### NPS6: Conformance and Hardening

- Keep core `PersistentLog` conformance distinct from Nestpy adapter
  lifecycle/execution conformance.
- Exercise broker and external checkpoints, reconnect generations, duplicate
  records, checkpoint uncertainty, blocked partitions, backpressure, and lag.
- Add bounded status, safe diagnostics, redaction, and native unwrap tests.
- Prove coexistence with HTTP and `nestpy-microservices` without shared markers
  or dispatch bridges.

Exit gate: no failure advances an unsafe checkpoint, leaks work, or collapses an
indeterminate outcome into success.

### NPS7: Acceptance and Release

- Add application examples for handlers and all publisher forms.
- Document replay, idempotency, retention gaps, checkpoint stores, and
  operations.
- Run focused and full pytest, Ruff, format, ty, documentation, and artifact
  gates through uv.
- Complete independent architecture, concurrency, reliability, security, and
  public-API review.

Exit gate: all architecture acceptance criteria pass from built artifacts.

## Deferred Work

- Multiple persistent-stream roots in one application.
- Parallel processing inside a physical partition.
- Automatic schema migrations or poison-record skipping.
- Exactly-once processing or transactional checkpoint/effect coordination.
- CQRS, EventDispatcher, domain-event, or event-store bridges.
- Stream administration UI, AsyncAPI, and schema registry integration.
