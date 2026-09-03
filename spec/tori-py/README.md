# ToriPy Executable Specifications

These phase documents turn [`TORI_PY_ARCHITECTURE.md`](../../TORI_PY_ARCHITECTURE.md)
into implementation contracts. The architecture document owns the overall
design; these specifications own phase boundaries, required artifacts,
invariants, tests, and exit criteria.

## Terms

- **MUST**: required for the phase.
- **MUST NOT**: prohibited for the phase.
- **SHOULD**: default unless a documented implementation constraint justifies
  another choice.
- **MAY**: optional and must not weaken required behavior.

## Phase Map

| Phase | Specification | Depends on | Main result |
| --- | --- | --- | --- |
| N0 | [Workspace and contracts](phase-n0-workspace-and-contracts.md) | None | Package boundaries and public declarations |
| N1 | [Module compiler](phase-n1-module-compiler.md) | N0 | Immutable validated module/provider graph |
| N2 | [DI runtime and lifecycle](phase-n2-di-runtime-and-lifecycle.md) | N0-N1 | Scopes, resources, startup, shutdown |
| N3 | [Settings, logging, testing](phase-n3-settings-logging-testing.md) | N0-N2 | SettingsModule, logger, overrides |
| N4 | [Starlette HTTP](phase-n4-starlette-http.md) | N0-N3 | ASGI, controllers, raw binding, base Problem Details |
| N5 | [Pipeline and errors](phase-n5-pipeline-and-errors.md) | N0-N4 | Middleware through filters and validation errors |
| N6 | [CLI and hardening](phase-n6-cli-and-hardening.md) | N0-N5 | CLI, adversarial lifecycle and release gate |
| N7 | [Reflection and discovery](phase-n7-reflection-and-discovery.md) | N0-N6 | Typed metadata and compiled-provider introspection |
| N8 | [Exception-aware resource unwinding](phase-n8-resource-unwinding.md) | N0-N7 | Outcome-preserving request/work-scope cleanup |
| N9 | [First-class WebSockets](phase-n9-websockets.md) | N0-N8 | Native gateway connections through Starlette |

## Cross-Phase Invariants

1. Python target is 3.14.
2. Python environments, dependencies, commands, tests, and services use `uv`
   exclusively.
3. `tori_py.core` never imports Starlette, Uvicorn, FastAPI, Pydantic,
   `dependency_injector`, or `tori-py-cqrs-core`.
4. Providers and modules are registered explicitly; discovery inspects only the
   compiled application graph and never scans packages or uses a process-global
   registry.
5. Compilers inspect annotations once and freeze runtime plans. Runtime
   resolution does not repeat signature inspection.
6. Static modules are unique by class. Dynamic modules are unique by
   `(module class, key)` and reuse requires the same descriptor object.
7. Provider resolution order is local, direct imported exports, then global
   exports. Same-level ambiguity is an error.
8. Singleton providers cannot reach request-scoped providers through any
   dependency path.
9. Request/work scopes and their resolvers are bound to one owner task.
   Cross-task resolution is rejected, and shutdown does not close a request
   resource concurrently with its owner task.
10. `CancelledError`, `KeyboardInterrupt`, and `SystemExit` are never converted
    into HTTP responses by exception filters.
11. One monotonic deadline controls shutdown. Awaitable cleanup is bounded;
    lingering sync executor workers are observed and logged.
12. HTTP routing is delegated to Starlette. ToriPy does not implement a route
    matcher and only rejects exact duplicate normalized method/path identities.
13. HTTP binding extracts raw values. Typed conversion belongs to pipes.
14. Global pipeline tokens resolve from root-module visibility into qualified
    provider references.
15. Secret settings values are never accepted through CLI `--set`.
16. `X-Request-ID` is framework-owned and consistent across context, logs, and
    responses.
17. `@no_body` routes enforce the actual stream after guards and before binding
    or dispatch, and cannot also declare `Body()` or `BodyStream()`.
18. Examples live under root `examples/`, not framework package source.
19. A phase is complete only after its focused tests and the full workspace
    quality gates pass.
20. `BodyStream(max_bytes=...)` binds one single-consumer raw byte stream after
    guards and uses direct backpressured ASGI receiving with no framework
    prefetch queue. It enforces its route limit without parsing, spooling, or
    changing the global JSON body limit, has request lifetime, and must consume
    the final request message before a successful response.
21. While a body remains active, disconnect is observed by its next direct
    receive. A separate disconnect monitor starts only after body EOF because
    concurrent monitoring on ASGI's ordered channel would require prefetching.
22. A matched WebSocket connection owns one request scope from pre-handshake
    pipeline execution through disconnect, cancellation, or handler return.
23. WebSocket handlers receive native sockets explicitly and own handshake,
    frame, subprotocol, and close policy; ToriPy does not add a message envelope.

## Quality Gates

Every phase runs:

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check packages/tori-py-cqrs-core/src packages/tori-py-cqrs-core/tests packages/tori-py-cqrs-fastapi/src packages/tori-py-cqrs-fastapi/tests packages/tori-py/src packages/tori-py/tests
```

The type-check paths are extended only after the ToriPy package exists in N0.

## Change Control

When implementation requires a behavior change:

1. update `TORI_PY_ARCHITECTURE.md` when the architectural decision changes;
2. update the affected phase specification before code;
3. add a behavioral test that proves the new contract;
4. review downstream phase assumptions;
5. do not silently resolve design questions in implementation.

`tori-py-cqrs` discovery is specified separately in C2 and consumes only public
N7 contracts.
