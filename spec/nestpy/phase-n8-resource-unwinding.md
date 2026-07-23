# N8: Exception-Aware Resource Unwinding

## Purpose

Preserve active execution failures while all request/work-scope resources unwind,
and expose cleanup failures without silently replacing control flow.

## Contract

- Every managed provider resource is exited once in LIFO acquisition order.
- Every exit receives the original body exception tuple.
- Managed provider resources cannot suppress body exceptions; truthy exit results
  are invalid resource results.
- Ordinary cleanup failures are collected while remaining exits continue.
- `ScopeFinalizationError` carries the original ordinary body error, when any,
  and ordered cleanup failures.
- `ScopeCancellationError` is a `CancelledError` subtype carrying original
  cancellation and cleanup failures.
- `KeyboardInterrupt` and `SystemExit` remain the same objects; cleanup failures
  are logged and attached as notes.
- Without cleanup/invalid-exit failures, a normal result or original body
  exception passes through unchanged.
- Scope close remains shielded and bounded according to existing lifecycle rules.
- Invocation owners can inspect final scope completion after all resources close.
- Public `WorkScopeFactory.application_id` exposes the driver-neutral kernel
  application identifier needed by non-HTTP execution contexts.

## Tests

- Clean body with one/multiple cleanup errors.
- Ordinary body failure with one/multiple cleanup errors.
- Cancellation with cleanup errors remains `CancelledError`.
- Keyboard/system exit identity and cleanup observation.
- Truthy suppression attempt is rejected.
- Nested resources receive original body failure and all exits are attempted.
- Request and CQRS work-scope shutdown behavior remains bounded.

## Exit Criteria

- No active execution failure is silently replaced or lost during resource
  cleanup.
