# Phase N6: CLI and Hardening

## Purpose

Add the conventional `tori-py run` command and perform adversarial hardening of
the complete v1 framework. N6 does not add another composition model or HTTP
driver.

## Entry Criteria

- N0-N5 pass focused and full workspace gates.
- Async exported factory and ASGI wrapper are stable.
- Settings BootstrapContext and secret paths are stable.

## Console Entry Point

Package metadata defines:

```toml
[project.scripts]
tori_py = "tori_py.cli:main"
```

`tori-py run module:factory` is the only v1 serving command.

Uvicorn is the only supported v1 CLI server and is imported lazily after CLI
parsing/factory validation. Missing CLI extra produces an actionable message
without traceback:

```text
The 'tori-py run' command requires the CLI extra.
Install it with: uv add 'tori-py-framework[cli]'
```

Importing `tori_py`, `tori_py.core`, or `tori_py.cli` without executing `run` MUST
NOT import Uvicorn.

## Factory Loading

CLI steps:

1. parse `module:factory` and non-secret `--set path=value` arguments;
2. import target module;
3. resolve named callable;
4. use `inspect.iscoroutinefunction` as a load-time qualification and reject
   clearly synchronous factories without calling them;
5. build immutable `BootstrapContext`;
6. wrap the factory so context remains set while ASGI lifespan awaits it; the
   N4 wrapper performs the authoritative runtime check that the result is
   awaitable and yields `NestApplication`;
7. call the existing `tori_py.starlette.asgi` wrapper;
8. lazy-import and run Uvicorn.

The CLI MUST NOT call `NestApplication.create()` itself, materialize modules, or
await the factory before handing the wrapper to the server. Factory, startup,
requests, and shutdown execute in the server event loop.

## CLI Overrides

Support repeated non-secret:

```text
--set namespace.path=value
```

Rules:

- path cannot be empty;
- final duplicate path wins;
- value remains text until settings decode;
- once SettingsModule identifies a path as `Secret[T]`, any CLI override for
  it is a bootstrap error;
- error output never echoes rejected secret values;
- secrets use explicit files, dotenv, or environment.

## Server and Lifespan

Uvicorn MUST run with lifespan enabled. CLI propagates startup/shutdown failure
as non-zero exit status. Interrupt signals trigger normal ASGI shutdown first.
The framework's bounded deadline remains authoritative; CLI does not start an
unbounded second cleanup path.

Development reload MAY be supported only if each worker/reload imports the
factory and creates a fresh application. Reload behavior MUST NOT reuse stopped
instances or duplicate singleton resources across workers.

## Hardening Matrix

N6 performs repository-wide adversarial testing for:

- module/provider/alias cycles;
- dynamic descriptor identity conflicts;
- scope-path violations;
- singleton and request construction races;
- partial resource acquisition and cleanup failures;
- sync executor workers past deadline;
- cancellation-resistant request tasks;
- stale request resolvers/context variables;
- lifecycle hook failure at every stage;
- exact-once startup/shutdown and ASGI lifespan failures;
- Starlette route ordering and exact duplicate detection;
- body limit under chunked receive;
- invalid/duplicate request IDs;
- catch-all filters under cancellation;
- errors after response transmission starts;
- settings source corruption and secret redaction;
- TestingModule override boundaries;
- CLI import/factory/extra/override failures.

## Performance Baseline

N6 adds repeatable microbenchmarks, not hard premature optimization. Measure:

- module graph compilation by module/provider count;
- singleton startup;
- request scope open/close;
- singleton/request/transient resolution;
- direct controller dispatch;
- pipeline overhead by component count;
- msgspec body conversion;
- settings source merge/decode.

Benchmarks record environment and results but do not replace behavioral tests.
Any unbounded per-request graph/signature inspection is a blocking finding.

The executable benchmark gate is:

```text
uv run pytest packages/tori-py/benchmarks --benchmark-only
```

## Security Baseline

Verify:

- no secret values in errors/logs/CLI diagnostics;
- YAML uses `safe_load`;
- body limits apply while streaming input;
- request IDs reject unsafe and duplicate input;
- Problem Details never expose tracebacks by default;
- filters cannot swallow cancellation/system exits;
- stale request resolvers fail closed;
- provider/module diagnostics do not render arbitrary secret object reprs;
- optional extras are imported only when used.

## Documentation and Examples

Provide:

- installation and extras;
- root module and async factory quickstart;
- provider/module visibility guide;
- scopes and resource ownership guide;
- controller/binding/MsgspecValidationPipe guide;
- complete global/controller/route pipeline order and cancellation behavior;
- lifecycle hooks, startup rollback, bounded shutdown, and lingering work;
- settings and secret handling guide;
- logging and request-ID behavior;
- testing override guide;
- CLI/server deployment guide;
- architecture limitations and deferred features.

Examples live under root `examples/tori_py/`, never under framework source. At
minimum include a multi-module HTTP app with settings, request provider,
controller, guard, MsgspecValidationPipe, filter, and deterministic shutdown.

## Release Quality Gates

Run all repository gates plus:

```text
uv lock --check
uv sync --locked
uv build --package tori-py-framework
```

Review public exports, dependency graph, license compatibility, package wheel,
source distribution, type markers, optional extras, and isolated import tests.
Install both wheel and source distribution into isolated `uv` environments and
run public-import plus minimal application smoke tests from each artifact.

Required artifact gate:

```text
uv run python packages/tori-py/scripts/verify_artifacts.py dist/
```

The script creates isolated `uv` environments for the wheel and source
distribution, imports every documented public facade, boots the documented
minimal application, executes one HTTP request, and shuts it down.

Required documentation/example gate:

```text
uv run pytest packages/tori-py/tests/docs examples/tori_py
```

The release checklist records manual evidence that every required guide exists
and matches public imports; executable snippets and the required example are
smoke-tested by the command above.

## Explicit Non-Goals

N6 MUST NOT:

- add another HTTP driver;
- add CQRS integration;
- add WebSockets/templates/static APIs;
- add an ORM/auth/job framework;
- relax phase contracts merely to make hardening tests pass.

## Tests

Tests MUST cover every hardening/security item above, plus:

1. CLI help/version without Uvicorn import;
2. missing/invalid module or factory;
3. async factory acceptance and synchronous/non-awaitable factory rejection;
4. factory executes in Uvicorn/server loop;
5. BootstrapContext reset after factory failure;
6. missing CLI extra message;
7. repeated overrides and secret override rejection;
8. signal-driven graceful shutdown;
9. non-zero exit on startup/shutdown failure;
10. reload creates fresh application instances if reload ships in v1;
11. wheel and source-distribution installation and public imports;
12. core isolation in an environment without optional extras;
13. no leaked tasks/resources/executor futures after cooperative tests;
14. lingering non-cooperative work emits expected diagnostics.
15. required example boots and serves one smoke request using only documented
    public imports.

## Exit Criteria

N6 and ToriPy v1 are complete when CLI serving uses the exact production ASGI
lifecycle, all adversarial lifecycle/security/import tests pass, package
artifacts install cleanly, documentation/examples match runtime behavior, and
the executable benchmark gate records the release baseline without unbounded
runtime graph/signature inspection, and independent review reports no required
findings.

The subsequently implemented `tori-py-cqrs` bridge is specified under
`spec/tori-py-cqrs/` and remains outside this N6 phase and release gate.
