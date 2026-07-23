# Phase 7: Command Reentrancy Guard

## Purpose

Reject same-bus nested command execution before transport enqueue so a handler
cannot deadlock a single-worker request transport or cause delayed execution after
its outer command times out.

## Contract

- A command dispatcher marks the active `CommandBus` identity in invocation-local
  context while its handler runs.
- `CommandBus.execute()` checks that identity before invoking
  `Transport.request()`.
- Executing through the same active bus raises core-owned
  `NestedCommandDispatchError` before enqueue.
- The rejected nested command is never delivered later.
- Different command-bus instances remain independent.
- Nested query and event operations retain their existing contracts.
- Class handlers, function handlers, and provider adapters observe the same rule.
- Context state is removed after success, failure, and cancellation and does not
  leak into unrelated tasks.

## Tests

- Same-bus nested execute fails immediately and never reaches transport.
- Timeout around a rejected nested execute cannot cause delayed delivery.
- Different buses can execute independently.
- Failure/cancellation clears active-bus context.
- A child task retained beyond outer handler completion cannot inherit active-bus
  state into a later unrelated dispatch.
- Existing top-level concurrent command behavior is unchanged.

## Exit Criteria

- Every transport passes the pre-enqueue guard tests without learning handler or
  routing semantics.
