# NPS5: Runtime and Lifecycle

## Status

Complete.

## Purpose

Own deterministic topology preparation, partition intake, readiness,
quiescence, and shutdown around compiled handlers and publishers.

## Startup Contract

- Resolve options and adapter factory after graph compilation.
- Compile handlers and publishers before adapter I/O.
- Acquire adapter resources as managed singletons.
- Prepare or verify streams without opening consumer intake.
- Query exact checkpoints and partition assignments before bootstrap readiness.
- Start consumers only in `on_application_bootstrap()` after work admission.
- Await the adapter `start()` readiness barrier and require every partition task
  to signal intake entry or fail before publishing `RUNNING`.
- Treat any blocked required partition as not ready.
- A lease stopped during its initial readiness read fails startup; a consumer
  that exits while admission remains open blocks its partition and degrades
  readiness.
- Unwind every partial startup failure in reverse acquisition order.

## Runtime Ownership

- Each accepted delivery or publication belongs to one observed task.
- Adapter callbacks cross a short handoff barrier and never detach framework work.
- One concurrency limiter bounds all active partition attempts.
- Per-partition serialization remains independent of callback arrival order.
- Status changes are immutable, distinct, bounded, and generation-aware.

## Quiescence and Shutdown

1. close publisher admission under the same lock used to register accepted calls;
2. await the adapter `quiesce()` native-intake and callback-handoff barrier;
3. cross callback scheduling and handoff fences;
4. drain accepted record and publication tasks against the shared deadline;
5. allow successful scopes to checkpoint before completion;
6. cancel remaining work at deadline without advancing checkpoints;
7. wait for callback tails;
8. close adapter resources in reverse order.

No cleanup task continues unobserved after shutdown returns.
Adapter quiesce failure does not skip draining admitted work and remains the
primary error after the drain. Direct close cancels and awaits admitted
publication tasks before adapter close.

## Tests

- Standalone and Starlette hybrid lifecycle.
- Readiness only after checkpoint and partition preparation.
- Failure after each acquired resource and idempotent cleanup.
- Callback-before-cancel races and handoff/task/tail drain ordering.
- Active handler/publication graceful and forced shutdown.
- Reconnect status handoff without duplicate intake.
- No leaked task, work scope, adapter, or status listener.

## Exit Criteria

- Fake-adapter applications start, report readiness, quiesce, fail, and recover
  without detached work or unsafe checkpoints.
