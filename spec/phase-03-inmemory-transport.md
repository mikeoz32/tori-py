# Phase 3: InMemoryTransport

## Purpose

Implement the first concrete transport as a bounded, FIFO, async in-memory queue with explicit lifecycle and request/reply support.

## Entry Criteria

- Phase 1 envelope, reply, receipt, protocol, and lifecycle exception types are complete.
- Phase 2 dispatcher and bus facades can run against a transport test double.
- The event task contract is known well enough for the consumer callback to return `None` for event work.

## Topology

Create one transport instance for each bus:

- command transport;
- query transport;
- event transport.

Each instance has one worker and one queue. A shared transport is not part of the first slice.

The transport worker invokes the consumer supplied to `start()`. It never receives a registry and never performs message-type routing.

## Queue Items

The internal queue may use private item types, but it must distinguish:

- request item: envelope plus a reply future;
- publish item: envelope plus a receipt completion path.

The private queue item types must not leak through public protocols or exception attributes.

## Configuration

The constructor SHOULD allow configuration of:

- maximum queue size;
- default enqueue/request timeout;
- clock or ID factories for deterministic tests, if needed;
- worker naming/logging metadata.

Defaults must be bounded and documented. Do not use an unbounded queue merely to avoid deciding backpressure semantics.

## State Machine

Valid states:

```text
NEW -> RUNNING -> STOPPING -> STOPPED
```

Rules:

1. `start()` is valid only from `NEW`.
2. `start()` creates exactly one worker task and returns after the worker is ready to receive items.
3. `request()` and `publish()` are valid only in `RUNNING`.
4. `shutdown()` is idempotent after the first stop request.
5. `shutdown()` stops accepting new work, drains according to its deadline, then cancels remaining worker/task work.
6. Calls made after `STOPPED` raise a typed stopped exception.
7. Invalid transitions raise a typed lifecycle exception and do not create leaked tasks.

## Request Flow

The request algorithm is:

1. Validate running state.
2. Validate that the request envelope has a correlation ID.
3. Create a private future owned by the transport.
4. Wait for queue capacity until the caller timeout/deadline.
5. Enqueue the request item.
6. Await the reply future with the remaining caller timeout.
7. Validate that the reply correlation ID matches the request.
8. Return the reply envelope to the bus.

Caller cancellation MUST cancel only the waiting operation. The queued item and a handler already running must not be forcibly cancelled by the caller's cancellation.

If a caller stops waiting, the worker still completes the request. The transport must safely discard a late reply when its future has no active waiter and must not log an unhandled-future warning.

## Publish Flow

The publish algorithm is:

1. Validate running state.
2. Create or preserve message and delivery IDs according to the envelope factory contract.
3. Wait for queue capacity until the caller timeout/deadline.
4. Enqueue the publish item.
5. Return a delivery receipt immediately after enqueue.

The receipt MUST NOT wait for the worker to call the consumer or for event handlers to finish.

## Backpressure

The queue is bounded. If it is full:

- the caller waits for capacity;
- the configured timeout applies;
- timeout raises a typed queue-capacity or transport-timeout exception;
- events are never silently discarded because they are fire-and-forget;
- retry is not performed by the transport.

## Delivery Semantics

The implementation is at-most-once:

1. A queue item is removed for processing once.
2. A failed consumer invocation is not requeued.
3. There is no acknowledgement protocol.
4. There is no durable storage.
5. A process crash may lose queued or running items.

Attempt metadata exists for contract completeness but remains `1` in this implementation. It must not imply retry support.

## Worker Failure

The worker MUST not die silently if a consumer raises. For request items, the worker resolves the reply future with an error reply. For publish/event items, the bus/event error policy handles the failure. The worker continues processing later queue items unless the failure is an unrecoverable transport lifecycle error.

Worker task failures must be observable through logging and a typed lifecycle/error hook. Do not leave a failed worker task unobserved.

## Shutdown

`shutdown(timeout)` MUST:

1. transition to `STOPPING`;
2. reject new request/publish calls;
3. allow already queued work to drain;
4. wait for the worker until the deadline;
5. cancel the worker and remaining queue/task work after the deadline;
6. resolve or cancel pending request futures safely;
7. transition to `STOPPED`.

The event bus may have additional handler tasks beyond the transport worker. Phase 4 defines their drain ordering. The transport itself must not claim that event handlers completed.

## Deterministic Testing Hooks

Tests MAY inject a clock, UUID factory, or queue size to make IDs and timeout behavior deterministic. Production code must not require test hooks.

## Phase 3 Tests

Tests MUST cover:

1. request/publish before start;
2. start twice and shutdown state transitions;
3. one worker per transport;
4. FIFO ordering with one worker;
5. request result and reply correlation;
6. handler exception propagation through an error reply;
7. publish receipt timing;
8. bounded queue waiting and timeout;
9. cancellation while waiting for a reply;
10. late reply after caller cancellation;
11. at-most-once behavior after consumer failure;
12. shutdown drain success;
13. shutdown timeout and cancellation;
14. idempotent shutdown;
15. no leaked worker tasks after every test.

## Exit Criteria

Phase 3 is complete when all three buses can use separate `InMemoryTransport` instances for request/publish operations, and lifecycle/backpressure/cancellation tests pass through `uv`.
