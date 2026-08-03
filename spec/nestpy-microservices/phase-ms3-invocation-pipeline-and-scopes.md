# MS3: Invocation Pipeline and Scopes

## Purpose

Execute compiled RPC and event handlers with exact Nestpy DI ownership,
transport-neutral contexts, deterministic pipeline ordering, and settlement only
after scope finalization.

## Public Contracts

- `MessageContext` base implementing Nestpy `ExecutionContext`.
- `RpcContext` and `EventContext` immutable specialized contexts.
- Read-only message metadata, handler identity, attempt/redelivery data, and
  native `unwrap()` escape hatch.
- Typed invocation completion describing result availability, body failure,
  scope failure, encoded response, and settlement recommendation.
- Message-specific retry/reject/deadline/configuration errors.

## Scope Contract

- Every delivery attempt calls
  `WorkScopeFactory.run_in(handler.owner_module, operation)`.
- A fresh `contextvars.Context` prevents ambient HTTP or prior-message leakage.
- Request-scoped providers cache once within the attempt.
- Transient resources belong to that work scope.
- Controller and singleton dependencies retain normal application ownership.
- The resolver and context become invalid after scope closure.
- Child-task use of task-guarded resources remains the resource owner's concern
  and is not made safe by context copying.

## Pipeline Order

```text
filter boundary(
  global/controller/handler guards ->
  argument extraction ->
  global/controller/handler pipes per argument ->
  global/controller/handler interceptors ->
  handler -> result validation and encoding
)
```

- Interceptors unwind in reverse order.
- Every `next` callback is one-shot.
- Provider-backed components resolve lazily in visible chain order.
- Guard denial maps to a stable RPC/event authorization failure and never to an
  HTTP response.
- Pipes receive `ArgumentMetadata` identifying message handler and binding.
- Filters catch `Exception` only, never cancellation or process-control values.
- Event results other than `None` are configuration/runtime contract errors.

## Context Contract

- `execution_kind` is `rpc` or `event`.
- `application_id`, exact module label, handler ID, correlation ID, and resolver
  are available through portable properties.
- Transport metadata is immutable and size-bounded.
- Native context access is explicit and read-only by default.
- Context exposes no public ACK, NACK, requeue, channel, or connection mutation.
- Authentication/authorization facts are application-provided and never inferred
  from routing or reply headers.

## Completion and Settlement Boundary

- Handler success is provisional until interceptors and scope cleanup finish.
- RPC result encoding occurs before successful completion is reported.
- `ScopeFinalizationError` and `ScopeCancellationError` retain Nestpy semantics.
- Event ACK eligibility requires successful invocation and scope close. RPC
  completion may instead carry a handled/sanitized wire error, but still
  requires successful scope close before reply publication and settlement.
- Retry/reject classification observes the final composed error.
- A filter that converts an event error to success intentionally permits ACK and
  must be documented as such.
- Transport settlement occurs outside the closed scope and cannot resolve
  providers.

## Tests

- Exact pipeline entry and reverse-unwind order.
- One-shot `next` enforcement and interceptor short-circuiting.
- Singleton/request/transient handler dependency and enhancer scopes.
- Exact owner-module resolution with same tokens in different modules.
- Payload/header/context/injection binding and pipe ordering.
- Guard denial, filter replacement, handler failure, encoding failure.
- Body plus cleanup failure, cancellation plus cleanup failure, and
  process-control identity.
- Context and resolver invalidation after completion.
- No HTTP request/log context leakage between messages.
- Settlement callback cannot run before resource cleanup.

## Exit Criteria

- A fake encoded delivery can execute any compiled handler without importing a
  concrete broker.
- Completion contains enough information for every transport to settle without
  inspecting Nestpy internals.
