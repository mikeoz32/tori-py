# Nestpy Microservices Implementation Plan

## Status

Implementation status: the MS0-MS8 capability set is implemented in the current
worktree. MS9 is partial/in progress: RabbitMQ event routing, topology,
transport mechanics, and event-mode tests are implemented, but the required
application-facing `EventDispatcher` API owned by the local service root remains.
Focused package tests, in-memory transport conformance, and Docker-backed
RabbitMQ round-trip, redelivery, unroutable-publication, and shared conformance
tests are present.

MS10 hardening and MS11 release acceptance are not complete. In particular,
real broker restart/recovery and network-blackhole behavior have not been proven,
and no full quality, artifact, documentation, or independent-review gate is
claimed by this status update.

| Phase range | Current status |
| --- | --- |
| MS0-MS6 | Implemented; focused contract, compiler, pipeline, in-memory, lifecycle, and client tests are present |
| MS7-MS8 | Implemented; targeted unit and Docker-backed RabbitMQ coverage is present, with the MS10 fault matrix still outstanding |
| MS9 | Partial/in progress; event routing, topology, transport mechanics, and event-mode tests are implemented; the root-owned application-facing `EventDispatcher` API remains |
| MS10 | In progress; broker restart, blackhole, reconnect-boundary, stale-delivery-tag, forced-shutdown, and complete observability/security hardening remain |
| MS11 | Not complete; examples, complete user/operations docs, full quality gates, built-artifact smoke tests, and independent release review remain |

Architecture:
[`NESTPY_MICROSERVICES_ARCHITECTURE.md`](NESTPY_MICROSERVICES_ARCHITECTURE.md).

Executable specifications:
[`spec/nestpy-microservices/README.md`](spec/nestpy-microservices/README.md).

## Delivery Principles

1. Specifications govern behavior before implementation chooses ambiguous
   semantics.
2. The smallest vertical contract is implemented and accepted before RabbitMQ
   complexity is added.
3. Nestpy core remains independent of the optional package.
4. All controller discovery uses public `DiscoveryService` and exact compiled
   module identities.
5. Every inbound attempt receives a fresh Nestpy work scope.
6. Transport adapters never own DI resolution or pipeline execution.
7. RabbitMQ topology and delivery guarantees are tested against a real broker.
8. Every Python environment, dependency, test, build, and service command runs
   through `uv`.
9. Public APIs, import boundaries, type markers, wheel contents, and sdist
   contents are release contracts, not follow-up cleanup.

## Delivery Order

### MS0: Workspace and Package Contracts

- Add `packages/nestpy-microservices` to the uv workspace.
- Add runtime dependencies only on `nestpy` and `msgspec`.
- Add the optional `rabbitmq` extra with `aio-pika>=10,<11`.
- Add `README.md`, `py.typed`, exact public facades, typed errors, and artifact
  verification scaffolding.
- Add import-boundary tests proving base imports do not load `aio_pika`,
  Starlette, SQLAlchemy, CQRS, event sourcing, or Kinker.
- Add package paths to Ruff, ty, and repository quality commands.

Exit gate: empty package artifacts install and import in isolation with the
documented optional-dependency boundary.

### MS1: Service Identity and Wire Contracts

- Implement immutable `ServiceIdentity`, RPC/event identities, message IDs,
  deadlines, and bounded metadata.
- Implement RPC request/response and event envelopes.
- Implement stable typed remote errors without Python exception paths.
- Implement codec protocols and deterministic msgspec JSON defaults.
- Reject invalid aliases, non-positive versions, malformed timestamps, unsafe
  headers, oversized headers/payloads, and ambiguous result/error responses.
- Freeze the wire compatibility and schema-evolution rules in tests.

Exit gate: all wire values round-trip deterministically and invalid wire input
fails before handler or provider resolution.

### MS2: Controller Discovery and Handler Compiler

- Implement `@rpc(method)` and `@event_handler(...)` as immutable direct method
  metadata.
- Discover every explicitly registered controller through `DiscoveryService`.
- Inspect direct methods only and retain exact `ProviderRef` and `ModuleId`.
- Compile payload/context/header/injection parameters and return annotations.
- Enforce unique RPC aliases, stable event subscriptions, async handlers, and
  explicit return contracts; MS5 owns the application-level one-root invariant.
- Export a public transport-neutral per-controller compiler for future tooling.
- Do not open transports or instantiate scoped providers during discovery.

Exit gate: a multi-module application produces one deterministic immutable
handler registry before transport intake.

### MS3: Invocation Pipeline and Work Scopes

- Implement `RpcContext` and `EventContext` as Nestpy `ExecutionContext`
  implementations.
- Qualify global/controller/handler guards, pipes, interceptors, and filters.
- Resolve provider-backed components through exact handler-owner visibility.
- Execute every attempt through `WorkScopeFactory.run_in()`.
- Keep `next` callbacks one-shot and provider resolution lazy.
- Decode payloads before invoking the handler and encode validated RPC results.
- Preserve cancellation, body errors, scope finalization errors, and typed
  completion outcomes without suppression.

Exit gate: transport-free invocation tests prove exact pipeline order, scope
ownership, context isolation, and cleanup-before-completion.

### MS4: Transport Contracts and In-Memory Conformance

- Implement server/client transport protocols, encoded delivery contracts,
  settlement outcomes, status streams, and native unwrap contracts.
- Implement a deterministic bounded in-memory broker.
- Model service queues, wildcard RPC routing, competing consumers, replies,
  publisher acceptance, manual settlement, redelivery, and all event modes.
- Make the in-memory transport explicitly non-durable.
- Create a transport conformance suite reusable by RabbitMQ.

Exit gate: two simulated replicas and all event modes pass without RabbitMQ or
private Nestpy APIs.

### MS5: Service Runtime and Lifecycle

- Implement `MicroservicesModule.for_root()` and enforce zero or one service
  root per application, including duplicate identities under different keys.
- Acquire the handler registry and transport as singleton managed resources.
- Prepare topology without intake during singleton startup.
- Start intake in `on_application_bootstrap()` after work admission opens.
- Track every accepted delivery task and enforce service-wide concurrency.
- Stop intake first and drain accepted tasks in
  `on_application_quiesce(context)` using the shared deadline.
- Make partial startup rollback and fallback resource cleanup idempotent.
- Add a standalone async runner while preserving Starlette hybrid lifecycle.

Exit gate: standalone and hybrid in-memory applications have deterministic
readiness, rollback, quiescence, and shutdown.

### MS6: ServiceCluster Client and Reply Router

- Implement `ServiceCluster`, immutable service proxies, and explicit
  `request(method, ...)` calls.
- Implement finite timeout validation, absolute deadlines, correlation IDs,
  causation IDs, and optional idempotency keys.
- Share one bounded reply router across every target service.
- Handle normal, remote-error, timeout, caller-cancellation, late, duplicate,
  unknown, and malformed replies.
- Mark pending requests indeterminate on reply transport loss and never
  automatically resend them.
- Implement `ClientsModule.register_cluster()` and `ServiceClusterOptions` as
  normal keyed Nestpy providers independent of the service root.

Exit gate: concurrent calls to several services use one reply router and retain
correct timeout/cancellation/indeterminate semantics.

### MS7: RabbitMQ Foundation and Topology

- Implement lazy optional imports and immutable RabbitMQ options.
- Implement one managed robust connection per keyed RabbitMQ root.
- Separate consumer, publisher-confirm, and reply channels.
- Implement deterministic exchange, queue, binding, and argument compilation.
- Declare durable topic exchanges, quorum durable queues, and classic temporary
  queues according to the architecture.
- Treat inequivalent existing topology as startup failure.
- Add real RabbitMQ tests for ownership, reconnect, confirms, mandatory returns,
  channel affinity, and cleanup.

Exit gate: RabbitMQ resources start, recover, and close without message handler
logic or leaked channels/tasks.

### MS8: RabbitMQ RPC Service Cluster

- Declare one queue per logical service and one wildcard binding
  `<namespace>.<service>.v<version>.*`.
- Publish each method call with its method-specific routing key.
- Register one equal-priority competing consumer per replica.
- Enforce bounded prefetch and service-wide concurrency.
- Implement unknown-service and unknown-method behavior as distinct outcomes.
- Implement deadline-bound backlog with broker expiration and server checks.
- Publish confirmed and routed replies before normal ACK; attempt terminal ACK
  for a proven deleted reply route without intentional requeue while preserving
  ACK uncertainty as a possible redelivery.
- Preserve at-least-once execution and duplicate-reply behavior under failures.

Exit gate: multi-process/multi-application tests demonstrate balanced service
cluster consumption, redelivery, deadlines, and response-before-ACK ordering.

### MS9: Clustered Event Dispatch

- Implement the application-facing `EventDispatcher` API owned by the local
  service root.
- Implement source-service event exchanges and typed event publication.
- Route and bind events by both alias and schema version.
- Implement `SERVICE_POOL` stable per-handler-pool queues.
- Implement explicit global `SINGLETON` subscription queues.
- Implement ephemeral and reliable `BROADCAST` per-instance queues.
- Require stable subscription identities for durable handlers.
- Include complete source identities in all event queues and complete
  destination identities in destination-scoped `SERVICE_POOL` and `BROADCAST`
  queues; global `SINGLETON` intentionally has no destination.
- Keep producer dispatch independent of consumer delivery modes.
- Implement bounded retry, terminal reject, dead-letter, and settlement policy.

Exit gate: a real RabbitMQ matrix proves exact queue counts and one-per-pool,
one-global, and every-instance delivery semantics.

### MS10: Failure Recovery and Hardening

- Test server and client reconnect at every request/reply/ACK boundary.
- Test publisher-confirm NACK, unroutable publication, channel closure, stale
  delivery tags, broker restart, and forced shutdown.
- Bound every payload, header set, pending request map, queue, task set, timeout,
  retry, and log path.
- Add structured status, readiness, diagnostics, metrics hooks, and safe logging.
- Validate TLS and RabbitMQ permission guidance without owning deployment
  configuration.
- Run fault-injection tests with a network proxy where practical.

Exit gate: no failure path silently converts an indeterminate outcome into
success, retries RPC automatically, leaks a task, or exceeds the application
shutdown deadline without diagnostics.

### MS11: Acceptance, Documentation, and Release

- Add standalone RPC service, clustered replicas, hybrid HTTP/RPC, and all event
  mode examples.
- Document topology, deadlines, idempotency, duplicate execution, broker
  policies, optional dependencies, testing, and operations.
- Run package and full repository pytest suites through uv.
- Run Ruff lint and format checks.
- Run ty against every configured package and example path.
- Build wheel and sdist and run isolated smoke tests with and without the
  RabbitMQ extra.
- Complete independent architecture, concurrency, reliability, security, and
  public-API review and resolve all findings.

Exit gate: all architecture acceptance criteria and repository quality gates
pass from built artifacts.

## Cross-Phase Test Matrix

Every phase adds focused tests and retains these cumulative requirements:

- exact public API and dependency allowlists;
- immutable options, plans, envelopes, and metadata;
- dynamic descriptor identity and one-service-root diagnostics;
- discovery of controllers across modules without package scanning;
- exact module-qualified resolution under duplicate class tokens;
- final testing override behavior;
- singleton, request, and transient scope ownership;
- no HTTP/log/message context leakage across attempts;
- cancellation and resource-cleanup error preservation;
- startup failure rollback and shutdown deadline propagation;
- bounded concurrency, prefetch, pending replies, and queues;
- unknown service, method, schema, reply, and subscription behavior;
- duplicate delivery, duplicate reply, and late reply behavior;
- two and three replica balancing without strict round-robin claims;
- all three event modes and reliable/unreliable broadcast;
- RabbitMQ connection, channel, topology, confirm, ACK, requeue, and DLX paths;
- Starlette coexistence and standalone lifecycle;
- artifact installation and lazy optional imports.

## Deferred Work

- Multiple logical service identities in one `NestApplication`.
- Streaming or bidirectional RPC.
- Remote cancellation guarantees.
- Kafka, NATS, Redis, MQTT, gRPC, WebSocket, or RabbitMQ Stream transports.
- AsyncAPI generation.
- Service membership registry or live replica discovery.
- Automatic outbox, inbox, saga, workflow, or distributed transaction support.
- Automatic CQRS, domain-event, or event-sourcing publication.
- Kinker service extraction or replacement of current linearizable policy ports.
- Framework-owned RabbitMQ deployment, users, vhosts, policies, or migrations.
