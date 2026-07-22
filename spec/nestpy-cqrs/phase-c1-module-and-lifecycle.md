# C1: Scoped Module and Lifecycle

## Purpose

Provide a dynamic Nestpy module whose CQRS handlers use Nestpy scopes and whose
buses participate in startup and quiescence.

## Contract

- `CqrsModule.for_root()` accepts explicit imports, bindings, options, key, and
  global visibility.
- Every binding compiles a private alias to a visible Nestpy provider token.
- One work scope is opened per command, query, or individual event-handler
  invocation through `WorkScopeFactory.run()`.
- Singleton, request, and transient behavior comes only from Nestpy provider
  declarations.
- Handlers expose async `handle()`; functions are not supported initially.
- Event, query, then command buses start before request admission.
- Command, query, then event buses stop during quiescence while work scopes
  remain admissible.
- One decreasing `ShutdownContext` budget governs bus shutdown.
- Partial startup rolls back all attempted buses.
- Acquired transports close if graph assembly or application startup fails.
- One transport object returned by multiple factories closes once on assembly
  failure; secondary cleanup failures are logged without hiding the primary
  failure.
- Event failure metadata identifies the configured provider token, not a private
  bridge marker.

## Verification

- command/query results use DI-created handlers;
- event fan-out preserves registration and scheduling order while handlers run
  in independent scopes; handler start and completion order are not guaranteed;
- scoped resources close on success, failure, and cancellation;
- HTTP ambient context does not reach handlers;
- startup rollback and shutdown drain are exact once;
- transport factory failure and lifecycle cancellation preserve cleanup and
  cancellation semantics;
- Starlette and CQRS modules coexist in one application.
