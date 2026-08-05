# MS5: Service Runtime and Lifecycle

## Status

Implemented. The module root, one-service-root validation, handler-driven
runtime, bounded admission/concurrency, startup rollback, quiesce, and close
paths are present. Standalone/hybrid examples and final acceptance remain MS11.

## Purpose

Compose discovery, invocation, transport, task ownership, readiness, and
bounded shutdown as one lifecycle-managed Nestpy subsystem.

## Module Contract

```python
MicroservicesModule.for_root(
    identity,
    transport=...,
    options=...,
    imports=...,
    key="default",
)
```

- Arguments are validated eagerly and defensively frozen.
- Descriptor materialization registers providers only; it performs no
  discovery, user factory execution, event-loop access, or transport I/O.
- One application may contain at most one service root.
- Root infrastructure is not globally exported unless a documented client or
  dispatcher token requires it.
- Keyed tokens remain deterministic and collision-safe.

## Startup Contract

1. Nestpy compiles modules/providers/controllers.
2. Singleton registry provider discovers and compiles all controllers.
3. Runtime acquires transport resources and prepares topology with intake off.
4. Module/provider initialization completes.
5. Nestpy driver binding completes.
6. Nestpy opens work-scope admission.
7. Service runtime starts only RPC/event consumers in
   `on_application_bootstrap()`; the independent MS6 client runtime owns reply
   consumption.
8. Runtime waits until every required consumer reports ready.
9. Startup returns and normal HTTP request admission may open.

No delivery callback may open a work scope before step 6 or after intake is
closed.

## Accepted Task Ownership

- Transport intake atomically checks admission and transfers each accepted
  delivery to one runtime-owned task; no transport callback may detach handler
  work.
- Task creation occurs in a fresh context or delegates to
  `WorkScopeFactory.run_in()` which does so.
- A service-wide semaphore limits active invocations.
- Sum of per-consumer prefetch is at most `max_inflight_deliveries`; startup
  rejects more consumers than the configured budget can assign one slot each.
- No callback waits behind the service semaphore while holding an accepted
  delivery outside the task bound.
- Task completion is observed exactly once, including cancellation/failure.
- Detached handler, reply, settlement, reconnect, or cleanup tasks are invalid.

## Quiescence Contract

`on_application_quiesce(context)`:

1. atomically closes runtime intake admission;
2. cancels native consumers and waits for cancellation acknowledgement;
3. invokes the transport's bounded intake-fence operation so no callback can
   later transfer accepted application work;
4. waits for accepted tasks using `context.remaining()`;
5. preserves time for Nestpy scope cancellation and resource cleanup;
6. cancels remaining owned tasks when the available budget expires;
7. leaves uncertain native deliveries unsettled or requeues only when channel
   state proves that operation safe;
8. returns without unbounded background cleanup.

The Nestpy kernel then closes work admission and drains/cancels tracked scopes.

## Startup Rollback and Close

- Every attempted consumer/resource is included in rollback, even if start
  failed midway.
- First failure remains primary while remaining cleanup is attempted.
- Runtime resource close is an idempotent fallback after normal quiescence.
- Process-control exceptions retain identity.
- A transport or task that ignores cancellation is logged with stable
  diagnostics and never silently abandoned.

## Standalone and Hybrid Hosting

- `NoopApplicationAdapter` supports a broker-only service.
- `StarletteAdapter` and `MicroservicesModule` share one Nestpy lifecycle for a
  hybrid HTTP/RPC/event service.
- An optional package runner creates, starts, waits for termination signals, and
  shuts down one application in one event loop.
- The runner is not a second composition or DI API.

## Tests

- Successful startup/readiness order.
- Consumer callback attempted before work admission is rejected.
- Failure during topology prepare, first/second consumer start, and readiness.
- Reverse rollback and exact resource close counts.
- Intake closure before accepted-task drain.
- Concurrent shutdown callers and cancellation of a shutdown caller.
- Shared decreasing deadline and forced cancellation.
- Broker-only and Starlette hybrid lifecycle.
- No delivery/task/resource remains after successful shutdown.

## Exit Criteria

- In-memory server startup means ready consumers, not merely allocated objects.
- Shutdown has the same bounded ownership guarantees as Nestpy HTTP and CQRS.
