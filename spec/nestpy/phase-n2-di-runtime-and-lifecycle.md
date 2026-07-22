# Phase N2: DI Runtime and Lifecycle

## Purpose

Execute N1 plans through a native async-first container with deterministic
scopes, resource ownership, eager singleton startup, rollback, and bounded
shutdown. This phase remains HTTP-driver independent.

## Entry Criteria

- N1 compiled graphs are immutable and deterministic.
- Provider keys, dependencies, canonical aliases, scope validation, and module
  order are complete.

## Runtime Components

N2 introduces:

- `Container`;
- application and request scope state;
- module-bound resolvers;
- invalidatable `ScopeLease`;
- resource stacks and cleanup records;
- sync resource executor runner;
- lifecycle orchestrator;
- internal `ApplicationKernel` and exact-once async `DriverBinder` protocol;
- monotonic deadline utilities.

The mutable container and scope caches are internal. Application code receives
only a module-bound `ScopedResolver`.

## Resolution

Resolution uses precompiled provider keys:

- singleton: eager application cache;
- request: one request-cache instance;
- transient: new instance on every resolution;
- alias: canonical target cache and identity.

Request cache creation is concurrency-safe. Concurrent resolution of one
request provider shares an in-flight future and creates one instance.
Cancelling one waiter does not remove or cancel authoritative in-flight
construction; the owning scope observes and closes it exactly once.

Transient resources inherit the current owner:

- singleton construction -> application resource stack;
- request execution -> request resource stack;
- nested transient -> current owner unchanged.

## Scope Lease

Each resolver checks a `ScopeLease` before resolution. Lease states are open,
closing, and closed.

- open permits resolution;
- closing rejects new resolution but allows task-owned cleanup;
- closed rejects all use with `ScopeClosedError`.

Request completion invalidates the lease exactly once and resets framework
context variables. Detached tasks retaining a resolver cannot acquire new
request providers after closure.

`WorkScopeFactory` is a reserved intrinsic dependency available to providers
without a declaration or export. It is bound to the receiving provider's exact
compiled module identity. `open()` creates an application-tracked work scope
that applies request/transient scope semantics. `run(operation)` additionally
executes the scoped operation in a fresh `contextvars.Context`; integrations use
it when work must not inherit HTTP or other ambient context. Direct `open()`
does not clear context variables. Explicit providers using the reserved token
are compilation errors.

## Resource Acquisition

Managed class/factory providers automatically enter returned context managers.
Managed values require `manage=True`; aliases never manage separately.

Async manager behavior:

1. resolve dependencies;
2. create manager;
3. await `__aenter__`;
4. expose entered value;
5. retain manager/exit callback for LIFO cleanup.

Sync manager behavior is identical but `__enter__`/`__exit__` execute in a
framework executor. Thread affinity is not guaranteed. Documentation and
runtime diagnostics MUST direct thread-affine resources to an async wrapper.

On acquisition failure, only resources acquired by that operation/scope segment
are closed in reverse order. The acquisition failure remains primary.

## Singleton and Module Startup

All singleton providers/controllers are eager. Module classes are instantiated
with no arguments for lifecycle hooks.

Startup order:

1. enter starting state;
2. instantiate modules in compiled module order;
3. construct singleton providers/controllers in dependency order;
4. enter resources before exposing them to dependents;
5. invoke `on_module_init` on modules, then singleton values;
6. invoke the configured `DriverBinder.bind()` exactly once;
7. open work-scope admission;
8. invoke `on_application_bootstrap` after the driver-binding hook;
9. open normal request admission and mark started.

Hooks MUST be async, accept only `self`, and complete successfully before the
participant enters rollback tracking.

The lifecycle marks driver binding attempted before awaiting `bind()`. The
binder must make partial bind failure observable and `close()` idempotent. Any
bind attempt, successful or failed, makes binder close eligible.

## Startup Rollback

If construction, resource enter, driver binding, or a hook fails:

1. preserve the first failure;
2. invoke `on_application_quiesce` only for participants whose bootstrap hook
   completed, while work admission remains open;
3. close work admission and drain active scopes;
4. invoke application-shutdown hooks only for participants whose bootstrap hook
   completed;
5. close the binder after reverse application-shutdown hooks when binding was
   attempted;
6. invoke module-destroy hooks only for participants whose module-init hook
   completed;
7. close resources in reverse acquisition order;
8. continue after secondary failures;
9. expose/log diagnostics for secondary cleanup failures;
10. finish in failed state.

## Request Scope Registry

N2 provides driver-neutral request/work scope primitives:

- separate normal-request and internal-work admission gates;
- active task registry;
- shared active-scope registry;
- scope context manager;
- active/closing/closed state transitions.

Normal drivers use `ApplicationRuntime.request_scope()`. Application subsystems
inject a module-bound `WorkScopeFactory`; they cannot access the kernel or open
normal driver scopes directly.

The future HTTP driver will own accepted task registration. N2 MUST NOT import
ASGI or Starlette.

## Shutdown

One monotonic deadline controls shutdown:

1. close normal request admission;
2. invoke reverse `on_application_quiesce(ShutdownContext)` hooks while work
   admission remains open;
3. close work admission;
4. compute a drain cutoff that reserves `cancellation_grace` and
   `cleanup_reserve` within the shared shutdown timeout;
5. wait for active scope tasks only until that drain cutoff;
6. cancel unfinished tasks;
7. wait `min(cancellation_grace, remaining_deadline)`;
8. mark remaining leases closing to reject new resolutions;
9. run reverse application-shutdown hooks;
10. invoke `DriverBinder.close()` exactly once when binding was attempted;
11. run reverse module-destroy hooks;
12. close application resources LIFO;
13. observe/log unfinished tasks/resources/workers;
14. return without unbounded detached cleanup.

Quiesce hooks receive the drain cutoff, are not started after their budget is
exhausted, and are cancelled and observed on timeout before teardown advances.
They MUST cooperate with cancellation. Cancellation observation is capped by
the reserved grace. If a hook still remains active, Nestpy closes admission,
drains tracked scopes, and deliberately skips binder/provider teardown rather
than race resource destruction against the lingering hook. Concurrent shutdown
callers join one shielded operation; cancelling one waiter never cancels
cleanup.

`ApplicationOptions` requires non-negative values and
`cancellation_grace + cleanup_reserve <= shutdown_timeout`.

Request tasks exclusively own request resource stacks. Shutdown MUST NOT call a
request resource exit concurrently with code still using it. A cancellation-
resistant task may leave resources open; the framework logs the leak at the
deadline.

Sync executor futures cannot be force-terminated. After the deadline the future
is observed and logged as lingering; Nestpy does not wait indefinitely or run
the exit twice.

## State Machine

```text
compiled -> starting -> started -> stopping -> stopped
                    \-> failed
```

Invalid transitions raise `ApplicationStateError`. A stopped/failed application
instance cannot restart.

## Explicit Non-Goals

N2 MUST NOT:

- create Starlette routes or ASGI apps;
- parse HTTP input;
- implement settings sources;
- implement testing overrides;
- implement middleware/guards/pipes/interceptors/filters.

N2 supplies a no-op binder for core tests. The public driver-neutral
`NestApplication` is owned by `nestpy.application`; concrete adapters are owned
by their driver packages. Public adapter implementations depend on the narrow
`ApplicationBinder` and `ApplicationRuntime` protocols plus immutable compiled
graph identities, not on `ApplicationKernel` internals.

## Tests

Tests MUST cover:

1. eager singleton construction order;
2. module classes with required constructor arguments are rejected;
3. request cache identity and transient non-caching;
4. concurrent request resolution creates one cached instance;
5. alias identity/cache/resource ownership;
6. runtime resolution of value, class, sync factory, async factory, and alias
   providers;
7. unmanaged ValueProvider default and managed `manage=True` behavior;
8. transient ownership matrix;
9. async context entered value and LIFO cleanup;
10. sync context executor offload;
11. partial acquisition rollback;
12. primary versus secondary failure preservation;
13. module/provider hook order;
14. synchronous hooks and invalid hook signatures are rejected;
15. startup rollback at every stage;
16. invalid state transitions;
17. lease invalidation and stale resolver rejection;
18. request task owns request resource cleanup;
19. graceful shutdown;
20. cancellation deadline and grace cap;
21. cancellation-resistant task diagnostics;
22. lingering sync worker diagnostics and stable diagnostic codes;
23. exact-once resource exits;
24. exact-once binder bind/close, partial bind failure, and later bootstrap
    failure rollback order;
25. drain cutoff preserves cancellation/cleanup time;
26. no core imports of Starlette.

## Exit Criteria

N2 is complete when a compiled non-HTTP application can start, resolve all
scopes, manage resources, roll back failures, and shut down under one bounded
deadline without leaking unobserved tasks/futures.
