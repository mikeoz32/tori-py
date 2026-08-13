# NES1: Invocation and Resource Foundation

## Entry Criteria

- NES0, ToriPy N8, ToriPy CQRS C3, event-sourcing ES6, and CQRS7 pass.

## Deliverables

- Integration contract tests against exception-aware ToriPy resources, public
  CQRS invocation interceptors, typed UoW outcomes/operation leases, and
  same-bus reentrancy rejection.

## ToriPy Resource Invariants

- RequestScope supplies the active body exception during LIFO cleanup.
- Every entered resource is offered cleanup exactly once.
- The primary body/control-flow exception is never silently replaced by a
  secondary cleanup error.
- Secondary failures remain inspectable.
- The work-scope owner distinguishes a clean body, failed body, and collected
  cleanup failures after all resources close.
- Cancellation during bounded cleanup remains observable and cleanup tasks are
  tracked according to existing ToriPy shutdown rules.

## CQRS Interceptor Invariants

- `CqrsInvocationContext` implements ToriPy `ExecutionContext` with
  `execution_kind == "cqrs"`.
- Context maps every `ExecutionContext` property exactly: application ID from the
  ToriPy kernel, string `module_id` label, `route_id=None`, `request_id=None`,
  scoped resolver, and immutable metadata. Exact values additionally use
  `owner_module: ModuleId` and `handler_ref: ProviderRef` properties.
- No HTTP request context propagates into CQRS execution.
- Interceptor tokens are qualified through final handler-owner visibility.
- Provider interceptors use normal singleton/request/transient semantics.
- Direct instances are externally owned.
- `next()` is callable once; a second call raises `CqrsPipelineStateError`.
- The terminal resolves the handler lazily after outer interceptors enter.
- Outer/system handler interceptors wrap graph interceptors, which wrap normal
  handler interceptors; unwind order is reversed.
- Every provider interceptor and the handler are resolved lazily at their point
  in the chain.
- Interceptor, handler, and cleanup failures propagate without transport-specific
  conversion.
- Factory-produced transactional handlers declare interceptor bindings explicitly;
  class metadata is never discovered by constructing a factory early.

## UoW Outcome Invariants

- Confirmed commit carries the validated `CommitResult`.
- Confirmed non-commit carries its cause where present.
- Indeterminate commit carries the original cause.
- Unknown errors after commit begins and malformed commit results are
  indeterminate.
- A validated commit remains confirmed through later cleanup failure.
- Outcome inspection is read-only and invalid before final classification.

## Tests

- Interceptor ordering, result transformation, one-shot `next`, and exceptions.
- Exact module visibility for private, alias, factory, and discovered handlers.
- Request/transient interceptor isolation and singleton reuse.
- No HTTP ContextVar leakage.
- Handler construction occurs inside the interceptor chain.
- Body failure plus one/multiple cleanup failures preserves all errors.
- Control-flow failure plus cleanup failure remains control flow.
- Every UoW commit/failure path produces the required typed outcome.

## Exit Criteria

- The integration can use only public upstream APIs.
- Existing HTTP, CQRS, lifecycle, and event-sourcing tests remain green.
