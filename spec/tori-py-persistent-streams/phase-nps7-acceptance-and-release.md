# NPS7: Acceptance and Release

## Status

Implementation, all seven stream review findings, and repository test, quality,
typing, documentation, and artifact gates are complete.

## Purpose

Complete user, operations, quality, artifact, and independent review gates from
built distributions.

## Documentation

- One-root synchronous and async configuration examples.
- Handler examples using typed payloads, context, pipes, and injected services.
- Raw, named, and Protocol-token publisher examples.
- Replay, at-least-once effects, idempotency, checkpoint timing, retention gaps,
  blocked partitions, and operator reset guidance.
- Adapter author guide and conformance-suite instructions.
- Explicit absence of EventDispatcher and automatic CQRS/event-store bridges.

## Verification

- Run package and full repository pytest suites through uv.
- Run Ruff lint and format checks through uv.
- Run ty against the package and every configured repository path through uv.
- Verify links, phase status, public API inventory, and package README.
- Build wheel and sdist, inspect contents, and smoke-test isolated installation.
- Confirm imports and dynamic descriptors perform no I/O or user factory call.

## Independent Review

- Architecture and package boundaries.
- Pipeline, scope, cancellation, and checkpoint correctness.
- Publisher typing, fixed policy, and indeterminate outcomes.
- Lifecycle, callback fencing, concurrency, and bounded shutdown.
- Security, privacy, observability, operations, and public API.

## Exit Criteria

- All architecture acceptance criteria pass from built artifacts.
- Every review finding is resolved or explicitly blocks release.
- Documentation contains no unimplemented capability claim.
