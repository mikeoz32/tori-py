# MS4: Transport Contract and In-Memory Broker

## Status

Implemented. The transport protocols, bounded non-durable in-memory broker, and
shared RPC/event transport conformance helper are present, with focused
in-memory coverage.

## Purpose

Freeze the server/client transport boundary and prove service-cluster semantics
with a deterministic in-memory implementation before adding RabbitMQ.

## Transport Contracts

- Encoded inbound delivery with routing identity, immutable headers, receive
  time, attempt/redelivery data, and opaque native value.
- Encoded outbound publication and broker-acceptance receipt.
- RPC reply publication contract.
- `ServerTransport` lifecycle for topology preparation, intake start,
  quiescence, status, native unwrap, and close.
- `ClientTransport` lifecycle for event publish, RPC request publish, reply
  intake, status, native unwrap, and close.
- Explicit `ACK`, `RETRY`, `REJECT`, and `UNSETTLED` outcomes. `UNSETTLED`
  performs no native settlement; transports model channel loss so the broker may
  redeliver under its finite delivery policy.
- Distinct confirmed, rejected, unroutable, unavailable, timeout, and
  indeterminate publication errors.

## Boundary Rules

- Transports receive an immutable handler/topology registry; they do not inspect
  decorators or controller classes.
- Transports invoke one framework dispatcher callback; they do not resolve
  providers or execute pipelines.
- Framework code classifies final completion; transports map classification to
  native settlement operations.
- Transport status is not service membership or application authorization.
- Native objects never enter portable envelopes.
- A transport implementation documents its actual durability, ordering,
  fan-out, and redelivery semantics.

## In-Memory Broker

The in-memory broker models:

- named topic exchanges and queues;
- one service wildcard binding;
- method-specific RPC routing keys;
- several consumers competing on one queue;
- bounded prefetch and per-replica capacity;
- manual settlement and redelivery;
- mandatory unroutable publication;
- publisher acceptance distinct from handling;
- one shared reply route and correlation map;
- `SERVICE_POOL`, `SINGLETON`, and `BROADCAST` event queue topology;
- explicit broker shutdown and queue/task draining.

The implementation is process-local, non-persistent, and not a simulation of
network partitions or RabbitMQ confirms.

## Determinism

- Tests control broker clock and scheduling where needed.
- Competing consumers use deterministic fair rotation among currently eligible
  consumers without claiming RabbitMQ's exact scheduling.
- Queue and pending-map limits fail explicitly.
- Redelivery increments attempt metadata and preserves message identity.
- Closing one consumer returns its unsettled deliveries to the queue.
- Duplicate settlement is an error.

## Conformance Suite

The reusable suite verifies:

- topology registration and route matching;
- broker acceptance and mandatory returns;
- one delivery per attempt;
- competing-consumer eligibility and bounded prefetch;
- ACK removal, retry redelivery, and reject terminal handling;
- reply correlation and unknown/duplicate reply handling;
- intake close before drain;
- close idempotency and no leaked tasks;
- transport status transitions;
- native unwrap behavior.

RabbitMQ later runs every applicable conformance case plus broker-specific
tests.

## Tests

- Two and three simulated replicas of one service.
- Several RPC methods through one wildcard-bound queue.
- Different services with isolated queues.
- Consumer saturation and recovery.
- Consumer close with unsettled delivery.
- Queue capacity, deadline expiry, and caller timeout.
- All event modes and multiple subscriptions for one event.
- Publish/close/cancel races and duplicate settlement.
- Base package imports without RabbitMQ.

## Exit Criteria

- Complete RPC and event application tests can execute without RabbitMQ.
- Transport implementations require no private Nestpy access.
- RabbitMQ work can focus on native topology and failures rather than redefining
  framework semantics.
