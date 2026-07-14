# Phase 6: Review and Hardening

## Purpose

Verify the first slice as a coherent library, find behavioral gaps, and make the public contract safe for future adapters without adding those adapters prematurely.

## Entry Criteria

- Phases 0-5 exit criteria are met.
- Full tests pass through `uv`.
- The profile acceptance fixture is repeatable and isolated.

## Verification Order

Run checks in this order:

1. package/import smoke checks;
2. core unit tests;
3. transport lifecycle and concurrency tests;
4. event task-management tests;
5. FastAPI adapter tests;
6. integration/profile acceptance tests;
7. complete test suite;
8. configured formatter/linter/type checker, if present.

The exact command list must be recorded after the tool configuration exists. Every command must be run via `uv`.

## Public API Review

Review every package-root export:

- message markers;
- decorators;
- envelope/reply/receipt types;
- transport and provider protocols;
- bus classes;
- builder and registry types;
- documented exception classes;
- FastAPI dependency/lifespan helpers.

Remove accidental exports of queue internals, private task records, test fixtures, or FastAPI implementation details.

## Dependency Boundary Review

Verify mechanically and by import test that:

1. core runtime metadata has no FastAPI dependency;
2. core source has no FastAPI, Pydantic, SQLAlchemy, broker, or DI imports;
3. FastAPI adapter imports core through its declared workspace dependency;
4. test-only packages are not runtime dependencies;
5. lockfile reflects the current workspace.

## Behavioral Review

Check these invariants explicitly:

- duplicate command/query handlers fail before workers start;
- event handlers can be zero, one, or many;
- a command result is returned by `CommandBus.execute()`;
- a query result is returned by `QueryBus.execute()`;
- event `publish()` returns after enqueue;
- event handler exceptions never escape `publish()`;
- event failures are observable through the error hook;
- request timeout does not forcibly cancel a started handler;
- queue saturation waits or times out, never silently drops;
- startup is explicit;
- shutdown drains until a deadline and leaves no unobserved tasks;
- at-most-once and non-durable semantics are documented;
- no implicit database transaction exists.

## Failure Injection

Add tests or test fixtures for:

1. handler construction failure;
2. handler exception;
3. event error-hook exception;
4. transport worker exception;
5. queue capacity timeout;
6. caller cancellation;
7. shutdown timeout;
8. duplicate registration;
9. missing registration;
10. invalid reply correlation;
11. FastAPI startup failure;
12. FastAPI provider cleanup failure.

Each failure must have a predictable exception/logging/cleanup outcome. Do not accept tests that merely assert that some exception occurred without checking state cleanup.

## Concurrency Review

Use deterministic barriers/events rather than sleeps wherever possible. Tests must prove:

- one-worker FIFO behavior;
- event handler task tracking;
- caller return before event completion;
- shutdown waiting and cancellation;
- no duplicate lazy-singleton initialization.

Avoid timing-sensitive tests that pass only under a particular machine load.

## Documentation Review

Before declaring the first slice complete:

1. update `CQRS_IMPLEMENTATION_PLAN.md` with any changed decisions;
2. update the affected phase specifications;
3. update `AGENTS.md` only for durable workflow/architecture constraints;
4. document commands that were actually verified;
5. document residual risks and intentionally deferred adapters.

## Explicit Residual Risks

The first slice is not production messaging infrastructure. It intentionally lacks:

- durable delivery;
- retry and dead-letter behavior;
- broker serialization and message versioning;
- transaction/outbox coordination;
- distributed tracing propagation;
- production database integration;
- full FastAPI request-scope dependency semantics for background event work.

These risks must remain visible until their own specifications exist.

## Exit Criteria

Phase 6 is complete when:

1. all configured checks pass through `uv`;
2. the dependency boundary is verified;
3. public exports and failure behavior are reviewed;
4. the profile flow is a repeatable acceptance test;
5. no unobserved worker or event tasks remain after tests;
6. residual risks and next adapters are documented;
7. the plan and specs agree with the implementation.
