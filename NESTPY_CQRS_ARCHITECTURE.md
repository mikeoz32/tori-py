# Nestpy CQRS Integration Architecture

## Boundary

`nestpy-cqrs` is an optional, driver-neutral integration package:

```text
nestpy-cqrs -> nestpy, cqrs-core
```

Neither `nestpy` nor `cqrs-core` imports the bridge. The bridge does not depend
on Starlette, FastAPI, Pydantic, or a process-global registry.

## Composition

`CqrsModule.for_root()` returns one keyed Nestpy `DeferredModule`. Handler
classes are registered once as ordinary Nestpy providers and decorated with
`cqrs-core` command, query, or event metadata. During bootstrap the integration
uses Nestpy `DiscoveryService` to inspect every provider in the compiled
application graph. It never scans Python packages or registers providers.

Explicit handler bindings remain an optional escape hatch for factory-produced,
undecorated, or intentionally overridden providers. Their normal Nestpy
visibility and export rules still apply. Discovered private providers do not
need to be exported or imported into the CQRS module.

The dynamic module exports `CqrsBuses`, `CommandBus`, `QueryBus`, and `EventBus`.
Applications may make that module global explicitly; global visibility is not
the default.

Each explicit handler binding creates a private local alias provider. Alias
compilation validates handler visibility and preserves the canonical Nestpy
provider scope. Discovered handlers retain their exact canonical `ProviderRef`
and owner `ModuleId`; aliases never register one provider twice.
Commands and queries retain one-handler CQRS semantics. Event bindings preserve
declaration order and allow multiple handlers for one event.

## Dispatch Scopes

The bridge supplies a custom CQRS `HandlerProvider`. Every command handler,
query handler, and individual event handler invocation runs through
`WorkScopeFactory.run()`:

1. create a fresh context-variable context;
2. open one module-bound Nestpy work scope;
3. resolve either the explicit private alias or the discovered provider from
   its exact owner module;
4. await `handler.handle(message)`;
5. close request/transient resources and invalidate the scope.

Singleton handlers reuse the application instance. Request-scoped handlers are
created once per invocation. Transient handlers are created per resolution.
Different event handlers always receive independent work scopes. No HTTP request
scope or ambient request context is propagated into CQRS work.

Handlers must expose an async `handle()` method. Function handlers are outside
the first integration slice.

## Lifecycle

The CQRS runtime is an eager Nestpy singleton lifecycle participant.

Startup order is:

1. build the explicit CQRS registry and three distinct transports;
2. start event delivery;
3. start query delivery;
4. start command delivery;
5. allow normal Nestpy request admission.

Partial startup failure shuts down every attempted bus in reverse order.
Transports returned by factories are owned by the runtime resource as soon as
they are acquired. Assembly failure, cancellation, or another participant's
bootstrap failure closes every acquired transport even when the CQRS bootstrap
hook has not run. Repeated factory returns of one transport identity are closed
once, and secondary cleanup failures are logged without replacing the primary
assembly or lifecycle failure.

During `on_application_quiesce(context)`, normal request admission is already
closed while work scopes remain available. The runtime shuts down command,
query, then event buses using one decreasing budget. This allows queued commands
to query or publish events, and queued queries to publish events. Event shutdown
drains tracked handler and observer tasks before Nestpy closes work admission.

Arbitrary nested dispatch cycles during shutdown are not guaranteed. Once a bus
starts stopping, new submissions to that bus are rejected by `cqrs-core`.

## Ownership

Nestpy owns handler construction, scopes, managed resources, and cleanup.
`cqrs-core` owns envelopes, routing, bus semantics, transports, task tracking,
and event failure observation. The bridge owns only explicit registration
mapping and lifecycle coordination.

Event failure hooks receive the configured Nestpy provider token or discovered
module-qualified provider identity rather than the bridge's private registration
marker.

The first implementation uses public `RegisteredHandler.target` identity to map
private factory markers back to Nestpy aliases. A future `cqrs-core` provider-key
contract may remove this concrete coupling without changing the public bridge
API.

## Non-Goals

- package scanning or provider auto-registration;
- HTTP request-context propagation;
- shared event-envelope scopes;
- function-handler DI;
- multiple unqualified CQRS graphs imported into one module;
- persistence, brokers, retries, sagas, or outbox behavior.
