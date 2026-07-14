# Phase 4: Event Task Management

## Purpose

Implement event-specific fire-and-forget behavior above the transport. `EventBus.publish()` must return after enqueue while event handlers remain observable, drainable, and safe during shutdown.

## Entry Criteria

- Phase 2 event registration and dispatch rules are complete.
- Phase 3 transport can enqueue event envelopes and invoke a consumer.
- The lifecycle owner can call bus shutdown with a deadline.

## Event Dispatch Contract

When the event transport worker invokes the EventBus consumer:

1. Resolve all matching event handler registrations.
2. Create a task for each handler execution according to the selected ordering policy.
3. Add every task to the EventBus tracked-task set before returning.
4. Attach a done callback or equivalent observer that consumes success/cancellation/failure.
5. Return `None` to the transport consumer.

The event consumer must return quickly after task registration. It must not await handler completion.

## Handler Ordering Decision

The first slice must explicitly choose one of these behaviors before implementation:

- concurrent handlers: all handlers for one event are scheduled independently; no completion order guarantee;
- sequential handlers: handlers are scheduled/awaited in registration order, but caller `publish()` still returns after the event task is registered;
- bounded event concurrency: concurrent scheduling with a configured limit.

The recommended initial behavior is concurrent handler tasks with no ordering guarantee, because the event API is fire-and-forget and events have no transactional ordering guarantee. If sequential behavior is selected, add a test that proves it and update this document.

Regardless of the choice, one transport worker still dequeues event envelopes sequentially. Handler task concurrency is a separate concern.

## Error Hook

Event handler exceptions MUST:

1. be caught by the task observer;
2. be associated with the event message ID, event type, and handler identity;
3. be sent to the configured async or sync error hook;
4. be logged with enough metadata to diagnose the failure;
5. not escape the earlier `EventBus.publish()` call;
6. not produce an unobserved task exception warning.

If the error hook itself fails, that failure must be logged and must not kill the event task supervisor.

The error hook does not retry, requeue, or dead-letter work in this phase.

## Task Tracking

The EventBus MUST maintain a set or equivalent registry of active event tasks.

Requirements:

- completed tasks are removed;
- cancelled tasks are observed and removed;
- failed tasks are observed, reported, and removed;
- task references are not retained forever;
- `drain()` waits for the tasks active at invocation and handles tasks spawned during drain according to a documented policy;
- task tracking is safe when multiple event envelopes are processed.

## Drain and Shutdown

The recommended shutdown sequence is:

1. stop event transport intake;
2. drain the event transport queue;
3. wait for tracked event handler tasks until the shared deadline;
4. invoke cancellation for remaining tasks after the deadline;
5. observe cancellation results;
6. finish transport shutdown and mark the bus stopped.

The implementation must not claim durable delivery. A crash or forced timeout can lose event work.

## Context and Metadata

Events do not require correlation or causation IDs in the first slice. Event handlers may receive message ID, delivery metadata, and headers through function `HandlerContext` if that context contract is finalized in Phase 2.

Do not introduce `contextvars` propagation or hidden event metadata inheritance unless the specification is updated first.

## Phase 4 Tests

Tests MUST cover:

1. publish returns before a blocking event handler completes;
2. every matching handler is tracked;
3. successful tasks are removed;
4. failed tasks invoke the error hook and do not fail publish;
5. error-hook failure is logged and contained;
6. multiple event handlers follow the selected ordering/concurrency rule;
7. drain waits for active handlers;
8. drain timeout cancels remaining tasks safely;
9. shutdown does not leave event tasks behind;
10. event handler failures do not kill the transport worker.

## Exit Criteria

Phase 4 is complete when fire-and-forget events are non-blocking to callers but fully observable through tests, logs, error hooks, and graceful shutdown.
