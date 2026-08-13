# ToriPy Documentation and Examples Plan

Status: proposed execution plan; implementation has not started.

ToriPy N0-N6 provide the initial framework implementation. This plan turns the
architecture, executable specifications, public API, and tested examples into a
complete user-facing documentation product. It is intentionally separate from
the implementation phase documents: phase documents define framework contracts,
while this plan defines how users learn and apply those contracts.

## 1. Goal

Create documentation comparable in scope and usability to mature framework
documentation such as NestJS, while remaining Python-native and exact about
ToriPy behavior.

The completed documentation must let a new user:

1. Install ToriPy and its optional extras.
2. Build and run a small HTTP application without reading framework source.
3. Understand modules, providers, scopes, resources, and lifecycle behavior.
4. Use controllers, raw bindings, validation, and the complete HTTP pipeline.
5. Configure applications without exposing secrets.
6. Test modules, providers, lifecycle failures, and HTTP behavior.
7. Deploy through the supported ASGI and CLI paths.
8. Understand v1 limitations and know when to use Starlette escape hatches.
9. Find API reference material for every documented public symbol.
10. Run every documented example from the repository.

## 2. Definition of Done

The documentation project is complete when all of the following are true:

- A version-controlled documentation site builds with `mkdocs build --strict`.
- The complete navigation described in this plan exists.
- Getting Started produces a working application from an empty directory.
- Every public v1 concept has a guide page, executable example, or explicit API
  reference entry.
- Every code block presented as runnable is executed by a test or included from
  a tested source file.
- Every example uses documented public imports except examples explicitly about
  internals or failure diagnostics.
- Atomic examples cover the matrix in section 10.
- Three reference applications cover composition across multiple concepts.
- Wheel and source-distribution verification imports documented public facades
  and boots a documented application.
- Internal links, navigation, imports, formatting, types, and tests pass in CI.
- Documentation does not promise behavior outside the approved v1 architecture.
- An independent technical review reports no required correctness findings.
- A writing review reports no unresolved navigation, terminology, or clarity
  blockers.

## 3. Source-of-Truth Rules

Documentation must not silently redefine framework behavior.

The authority order is:

1. `TORI_PY_ARCHITECTURE.md` owns architecture and v1 boundaries.
2. `spec/tori-py/` owns executable behavior contracts and failure semantics.
3. Public tests prove the implementation conforms to those contracts.
4. User guides explain the proven behavior without introducing new behavior.
5. API reference is generated from public source docstrings.

When documentation exposes a missing or contradictory behavior:

1. Stop writing the affected claim.
2. Record the mismatch in the current documentation task.
3. Update architecture/specification first if behavior must change.
4. Add or update behavioral tests.
5. Change implementation.
6. Resume documentation only after quality gates pass.

## 4. Scope

### 4.1 Included

- Installation and optional extras.
- Modules and provider visibility.
- Dependency injection and provider declarations.
- Singleton, request, and transient scopes.
- Managed resources and lifecycle hooks.
- Starlette-backed controllers and routes.
- Raw HTTP bindings.
- Middleware, guards, pipes, interceptors, and filters.
- Msgspec validation.
- Problem Details and request IDs.
- Settings, secrets, logging, and bootstrap overrides.
- TestingModule and ASGI testing.
- CLI, ASGI deployment, shutdown, and operational guidance.
- Public API reference.
- Atomic examples, recipes, and reference applications.
- Explicit v1 limitations and deferred features.

### 4.2 Excluded

- Built-in CQRS integration.
- FastAPI integration.
- ORM, database, migration, broker, or job-queue abstractions.
- Framework-managed authentication or authorization implementation.
- First-class WebSocket, templates, static files, or streaming APIs.
- Pydantic-specific documentation.
- APIs not present in the current public package.
- A second application composition model.

Starlette response escape hatches may be documented, but they must be labeled as
driver-specific and non-portable to future drivers.

## 5. Audiences and Learning Paths

### 5.1 New Python web developer

Path:

```text
Introduction -> Installation -> First Application -> Controllers -> Providers
-> Settings -> Testing -> CLI
```

### 5.2 Experienced FastAPI or Starlette developer

Path:

```text
Architecture Overview -> Modules -> Scopes -> Raw Binding -> Pipeline
-> Starlette Escape Hatches -> Testing
```

### 5.3 NestJS developer

Path:

```text
NestJS Concept Mapping -> Modules -> Providers -> Lifecycle -> Pipeline
-> Python-Specific Differences -> Limitations
```

### 5.4 Library or infrastructure author

Path:

```text
Dynamic Modules -> Tokens and Visibility -> Resource Ownership
-> Lifecycle -> Custom Codec/Decoder -> Testing Overrides -> API Reference
```

### 5.5 Operator

Path:

```text
CLI -> ASGI Deployment -> Configuration and Secrets -> Logging and Request IDs
-> Health Checks -> Graceful Shutdown -> Security Checklist
```

## 6. Documentation Tooling Decision

Default tooling for implementation:

- MkDocs for site generation.
- Material for MkDocs for navigation, search, code annotations, and versioned
  presentation.
- `mkdocstrings` with the Python handler for public API reference.
- `pymdown-extensions` snippets so guides can include tested source fragments.
- Pytest for executable examples and documentation smoke tests.
- Existing Ruff and ty configuration for Python embedded in docs support code.

These dependencies belong in a root `docs` dependency group and must not become
ToriPy runtime dependencies.

Expected commands:

```text
uv sync --locked --group docs
uv run --group docs mkdocs serve
uv run --group docs mkdocs build --strict
uv run pytest packages/tori-py/tests/docs examples/tori_py
```

If tooling compatibility with Python 3.14 blocks this choice, document the
specific incompatibility before selecting Sphinx or another generator. Do not
mix two documentation generators.

## 7. Target Repository Layout

```text
mkdocs.yml
docs/
  index.md
  why-tori-py.md
  concepts-map.md
  getting-started/
    installation.md
    first-application.md
    project-structure.md
    first-controller.md
    first-provider.md
    configuration.md
    testing.md
    next-steps.md
  fundamentals/
    modules.md
    dynamic-modules.md
    global-modules.md
    providers.md
    tokens.md
    dependency-injection.md
    visibility.md
    scopes.md
    resources.md
    lifecycle.md
    startup-rollback.md
    graceful-shutdown.md
  http/
    controllers.md
    routes.md
    route-ordering.md
    binding-overview.md
    body.md
    path.md
    query.md
    headers.md
    cookies.md
    context.md
    provider-injection.md
    responses.md
    problem-details.md
    request-ids.md
    body-limits.md
    starlette-escape-hatches.md
  pipeline/
    overview.md
    middleware.md
    guards.md
    pipes.md
    msgspec-validation.md
    interceptors.md
    filters.md
    ordering.md
    short-circuiting.md
    cancellation.md
  settings/
    overview.md
    files.md
    dotenv.md
    environment.md
    precedence.md
    nested-settings.md
    secrets.md
    cli-overrides.md
    custom-codecs.md
    testing.md
  observability/
    logging.md
    structured-fields.md
    request-correlation.md
    failure-diagnostics.md
  testing/
    overview.md
    provider-overrides.md
    module-overrides.md
    dynamic-module-identity.md
    asgi-testing.md
    lifecycle-testing.md
    resource-testing.md
    failure-testing.md
  cli/
    installation.md
    run.md
    factory-loading.md
    overrides.md
    troubleshooting.md
  deployment/
    asgi.md
    uvicorn.md
    reverse-proxy.md
    containers.md
    kubernetes.md
    health-and-readiness.md
    graceful-shutdown.md
    production-checklist.md
  security/
    overview.md
    secrets.md
    request-ids.md
    input-limits.md
    error-disclosure.md
    cancellation.md
  recipes/
    repository-provider.md
    request-resource.md
    authorization-guard.md
    custom-validation.md
    domain-error-filter.md
    external-http-client.md
    multiple-settings-modules.md
    testing-startup-failure.md
    background-work.md
  reference/
    public-api.md
    decorators.md
    providers.md
    protocols.md
    options.md
    errors.md
    lifecycle-hooks.md
    diagnostic-codes.md
  limitations/
    v1.md
    starlette-specific.md
    deferred-features.md
  contributing/
    documentation.md
    examples.md
    release-checklist.md
examples/tori_py/
  getting_started/
  modules/
  providers/
  lifecycle/
  http/
  pipeline/
  settings/
  logging/
  testing/
  operations/
  reference_apps/
packages/tori-py/tests/docs/
packages/tori-py/scripts/verify_docs.py
packages/tori-py/scripts/verify_artifacts.py
```

The existing `examples/tori_py/app.py` becomes either the Getting Started example
or the initial reference application. Do not maintain two divergent copies.

## 8. Navigation

The top-level site navigation must be stable and task-oriented:

```text
Home
Getting Started
Fundamentals
HTTP
Pipeline
Settings
Observability
Testing
CLI
Deployment
Security
Recipes
Examples
API Reference
Limitations
Contributing
```

Phase names such as N0-N6 must not appear in normal user navigation. They belong
only in contributor and architecture material.

## 9. Content Standards

### 9.1 Required page structure

Every concept guide must contain these sections when applicable:

1. Purpose.
2. Minimal example.
3. Complete example.
4. Execution semantics.
5. Failure behavior.
6. Testing example.
7. Production considerations.
8. Related API symbols.
9. Next steps.

### 9.2 Code rules

- Use Python 3.14 syntax consistently.
- Use `uv` in every environment, dependency, test, build, and run command.
- Prefer `from tori_py import ...` and documented public subpackage facades.
- Do not import private names beginning with `_` in user examples.
- Do not use test-only convenience APIs in production examples.
- Do not omit application shutdown in manually started examples.
- Use async factories consistently.
- Keep raw HTTP binding raw unless `MsgspecValidationPipe` is registered.
- Label Starlette-specific response behavior explicitly.
- Never put real secret values in examples.
- Do not use `example error` catch-all filters that conceal the demonstrated
  behavior; filters must either preserve useful Problem Details or demonstrate a
  specific mapping.

### 9.3 Terminology

Use these canonical terms:

| Preferred | Avoid |
| --- | --- |
| provider declaration | service registration magic |
| provider token | dependency name |
| module visibility | module scope visibility |
| request scope | request singleton |
| managed resource | auto-close object |
| application factory | app loader |
| raw binding | automatic validation |
| Problem Details | generic JSON error |
| request ID | trace ID, unless discussing external tracing |
| dynamic module identity | module instance name |

### 9.4 Runnable snippet policy

Runnable snippets must use one of these forms:

1. Included from a tested file under `examples/tori_py/`.
2. Included from a docs test fixture under `packages/tori-py/tests/docs/`.
3. A shell command executed by a docs smoke test.
4. Explicit pseudocode marked as non-runnable.

Copy-pasted executable snippets without a test are prohibited.

## 10. Atomic Example Catalog

Each atomic example lives at:

```text
examples/tori_py/<category>/<slug>/
  README.md
  app.py
  test_example.py
```

An example may omit `app.py` only when it demonstrates a compile-time failure or
a pure settings operation. Every example must state its purpose, command, output,
and related guide.

### 10.1 Getting Started examples

| ID | Directory | Behavior |
| --- | --- | --- |
| E001 | `getting_started/hello_world` | Smallest controller application |
| E002 | `getting_started/async_factory` | Compiled async factory |
| E003 | `getting_started/asgi_wrapper` | Explicit ASGI export |
| E004 | `getting_started/cli_run` | `tori-py run` serving path |
| E005 | `getting_started/project_structure` | Separate module/controller/provider files |
| E006 | `getting_started/first_provider` | Constructor-injected class provider |
| E007 | `getting_started/first_settings` | Minimal typed settings |
| E008 | `getting_started/first_test` | TestingModule plus HTTP request |

### 10.2 Module examples

| ID | Directory | Behavior |
| --- | --- | --- |
| E009 | `modules/static_imports` | Static module imports |
| E010 | `modules/exports` | Public provider export |
| E011 | `modules/private_provider` | Private visibility failure |
| E012 | `modules/re_export` | Explicit imported-token re-export |
| E013 | `modules/global_module` | Opt-in global provider visibility |
| E014 | `modules/dynamic_for_root` | Dynamic `for_root()` configuration |
| E015 | `modules/dynamic_keys` | Multiple dynamic identities by key |
| E016 | `modules/async_dynamic_module` | Awaitable materialization |
| E017 | `modules/import_cycle` | Typed module-cycle failure |
| E018 | `modules/dynamic_identity_conflict` | Descriptor identity failure |

### 10.3 Provider and DI examples

| ID | Directory | Behavior |
| --- | --- | --- |
| E019 | `providers/value` | ValueProvider |
| E020 | `providers/class` | `@injectable()` shorthand and ClassProvider |
| E021 | `providers/factory` | Sync and async FactoryProvider |
| E022 | `providers/alias` | Alias identity and ownership |
| E023 | `providers/string_token` | Explicit string token |
| E024 | `providers/class_token` | Class token |
| E025 | `providers/inject_marker` | `Annotated[..., Inject(...)]` |
| E026 | `providers/default_constructor_value` | Non-injected default parameter |
| E027 | `providers/duplicate_token` | Duplicate provider diagnostic |
| E028 | `providers/provider_cycle` | Constructor dependency cycle |
| E029 | `providers/alias_cycle` | Alias-cycle diagnostic |
| E030 | `providers/ambiguous_visibility` | Ambiguous imported export failure |

### 10.4 Scope and resource examples

| ID | Directory | Behavior |
| --- | --- | --- |
| E031 | `lifecycle/singleton_scope` | Singleton caching |
| E032 | `lifecycle/request_scope` | One instance per request |
| E033 | `lifecycle/transient_scope` | New instance per resolution |
| E034 | `lifecycle/scope_violation` | Singleton-to-request path rejection |
| E035 | `lifecycle/async_resource` | Async context manager provider |
| E036 | `lifecycle/sync_resource` | Executor-backed sync resource |
| E037 | `lifecycle/resource_lifo` | Reverse cleanup order |
| E038 | `lifecycle/partial_acquisition` | Nested resource rollback |
| E039 | `lifecycle/hooks` | Complete hook order |
| E040 | `lifecycle/startup_failure` | Startup rollback |
| E041 | `lifecycle/shutdown_timeout` | Bounded shutdown |
| E042 | `lifecycle/stale_resolver` | Request resolver fails after close |
| E043 | `lifecycle/concurrent_singleton` | One in-flight singleton construction |
| E044 | `lifecycle/request_cancellation` | Request cancellation and cleanup |

### 10.5 HTTP examples

| ID | Directory | Behavior |
| --- | --- | --- |
| E045 | `http/controller_prefix` | Controller and route path join |
| E046 | `http/path_binding` | Raw path value |
| E047 | `http/query_binding` | Raw query value |
| E048 | `http/repeated_query` | Repeated values remain a sequence |
| E049 | `http/header_binding` | Explicit header source |
| E050 | `http/cookie_binding` | Explicit cookie source |
| E051 | `http/json_body` | Raw JSON-compatible body |
| E052 | `http/optional_binding` | Defaults make missing input optional |
| E053 | `http/request_context` | RequestContext properties |
| E054 | `http/provider_injection` | Request provider injection in handler |
| E055 | `http/json_response` | Mapping/sequence/scalar encoding |
| E056 | `http/dataclass_response` | Dataclass encoding |
| E057 | `http/msgspec_response` | Msgspec Struct encoding |
| E058 | `http/explicit_response` | Starlette Response passthrough |
| E059 | `http/status_code` | Route status metadata |
| E060 | `http/body_size_limit` | Streaming body limit |
| E061 | `http/media_type` | JSON media type enforcement |
| E062 | `http/malformed_json` | 400 Problem Details |
| E063 | `http/request_id` | Accepted and generated request IDs |
| E064 | `http/request_id_hardening` | Invalid and duplicate IDs |
| E065 | `http/not_found` | 404 Problem Details |
| E066 | `http/method_not_allowed` | 405 and Allow header |
| E067 | `http/route_ordering` | Starlette declaration ordering |
| E068 | `http/trailing_slash` | `/x` versus `/x/` |
| E069 | `http/file_response` | Driver-specific FileResponse escape hatch |
| E070 | `http/streaming_response` | Scope through StreamingResponse |
| E071 | `http/background_response` | Scope through Starlette background work |

### 10.6 Pipeline examples

| ID | Directory | Behavior |
| --- | --- | --- |
| E072 | `pipeline/global_order` | Global token order |
| E073 | `pipeline/controller_order` | Controller token order |
| E074 | `pipeline/route_order` | Route token order |
| E075 | `pipeline/full_order` | Complete pipeline sequence |
| E076 | `pipeline/middleware_nesting` | Enter/unwind order |
| E077 | `pipeline/middleware_short_circuit` | Early PipelineResult |
| E078 | `pipeline/one_shot_next` | Second `next()` failure |
| E079 | `pipeline/guard_allow` | Guard success |
| E080 | `pipeline/guard_forbidden` | Guard false maps to 403 |
| E081 | `pipeline/custom_pipe` | Per-argument transformation |
| E082 | `pipeline/msgspec_body` | Body model validation |
| E083 | `pipeline/msgspec_scalar` | Query/path scalar conversion |
| E084 | `pipeline/msgspec_repeated` | Repeated value conversion |
| E085 | `pipeline/raw_without_pipe` | Annotation does not auto-convert |
| E086 | `pipeline/interceptor_nesting` | Before/after handler |
| E087 | `pipeline/interceptor_short_circuit` | Explicit response from interceptor |
| E088 | `pipeline/filter_precedence` | Route/controller/global order |
| E089 | `pipeline/filter_fallthrough` | Re-raise selects next filter |
| E090 | `pipeline/filter_failure` | Filter exception fallback |
| E091 | `pipeline/global_404_filter` | Partial context and global filter |
| E092 | `pipeline/cancellation` | Cancellation bypasses filters |
| E093 | `pipeline/encoding_failure` | Pre-start encoding error is filterable |
| E094 | `pipeline/after_start_failure` | No replacement response after start |

### 10.7 Settings examples

| ID | Directory | Behavior |
| --- | --- | --- |
| E095 | `settings/toml` | TOML file |
| E096 | `settings/json` | JSON file |
| E097 | `settings/yaml` | Optional YAML extra |
| E098 | `settings/yaml_missing_extra` | Actionable missing-extra error |
| E099 | `settings/dotenv` | Supported dotenv grammar |
| E100 | `settings/environment` | Prefix and `__` nesting |
| E101 | `settings/precedence` | Complete source precedence |
| E102 | `settings/deep_merge` | Mapping merge and scalar replacement |
| E103 | `settings/nested_model` | Nested typed settings |
| E104 | `settings/global_module` | Global settings exports |
| E105 | `settings/multiple_models` | Dynamic keys and multiple models |
| E106 | `settings/custom_codec` | Codec protocol implementation |
| E107 | `settings/custom_decoder` | SettingsDecoder replacement |
| E108 | `settings/secrets` | Secret path discovery and redaction |
| E109 | `settings/cli_override` | Non-secret `--set` |
| E110 | `settings/secret_cli_rejection` | Secret override rejected without echo |

### 10.8 Logging examples

| ID | Directory | Behavior |
| --- | --- | --- |
| E111 | `logging/default_logger` | Injectable Logger |
| E112 | `logging/bound_fields` | Immutable bound fields |
| E113 | `logging/request_correlation` | Request ID in structured payload |
| E114 | `logging/reserved_fields` | User fields cannot overwrite framework fields |
| E115 | `logging/resource_state` | Resource lifecycle diagnostics |
| E116 | `logging/python_configuration` | Python handlers and formatters |

### 10.9 Testing examples

| ID | Directory | Behavior |
| --- | --- | --- |
| E117 | `testing/value_override` | Replace exported provider with value |
| E118 | `testing/class_override` | Replace with class |
| E119 | `testing/factory_override` | Replace with factory |
| E120 | `testing/alias_override` | Replace with alias |
| E121 | `testing/global_override` | Override global export |
| E122 | `testing/static_module_identity` | Static module target |
| E123 | `testing/dynamic_module_identity` | `(class, key)` target |
| E124 | `testing/module_replacement` | Replace descriptor before materialization |
| E125 | `testing/private_override_failure` | Private provider rejection |
| E126 | `testing/http_request` | ASGI request through production scope |
| E127 | `testing/request_provider` | Request-scoped test dependency |
| E128 | `testing/resource_cleanup` | Production shutdown cleanup |
| E129 | `testing/startup_failure` | Failure before resource creation |
| E130 | `testing/builder_sealed` | Late override rejection |

### 10.10 CLI and operations examples

| ID | Directory | Behavior |
| --- | --- | --- |
| E131 | `operations/cli_run` | Supported serving command |
| E132 | `operations/cli_overrides` | Repeated `--set`, final value wins |
| E133 | `operations/invalid_factory` | Sync factory rejection |
| E134 | `operations/missing_cli_extra` | Actionable Uvicorn-extra message |
| E135 | `operations/asgi_export` | Direct ASGI hosting |
| E136 | `operations/health_endpoint` | Liveness endpoint |
| E137 | `operations/readiness_endpoint` | Application readiness contract |
| E138 | `operations/graceful_shutdown` | Signal-driven normal shutdown |
| E139 | `operations/reverse_proxy_ids` | Proxy-safe request ID handling |
| E140 | `operations/container` | Container command and shutdown |
| E141 | `operations/kubernetes` | Probe and termination configuration |
| E142 | `operations/import_boundaries` | Optional integrations remain lazy |

The catalog is intentionally broad. It should be delivered in waves rather than
as 142 empty directories.

## 11. Reference Applications

### 11.1 Task API

Path: `examples/tori_py/reference_apps/task_api/`

Required concepts:

- AppModule, TasksModule, and InfrastructureModule.
- Typed settings with environment override.
- In-memory repository as an explicit provider.
- Request-scoped unit-like resource without introducing an ORM abstraction.
- Create/list/get task endpoints.
- Msgspec request validation.
- Authorization-shaped guard with a clearly fake policy.
- Domain exception filter.
- Structured logger and request ID.
- Provider override tests.
- Startup and shutdown tests.
- CLI and direct ASGI entry points.

### 11.2 Community API Skeleton

Path: `examples/tori_py/reference_apps/community_api/`

Required concepts:

- Profiles, Groups, Posts, Moderation, and Chats modules.
- Privacy and moderation represented as domain/application provider boundaries.
- In-memory storage only.
- HTTP-only chat endpoints; no WebSocket claim.
- Guard ordering for membership and moderation checks.
- Request-scoped actor context.
- Problem Details for access denial and moderation failures.
- Dynamic settings module.
- Testing overrides for repositories and policy providers.
- Explicit note that CQRS, persistence, and authentication are deferred.

### 11.3 Production Blueprint

Path: `examples/tori_py/reference_apps/production_blueprint/`

Required concepts:

- Environment-specific settings without implicit directory scanning.
- Secret fields supplied through environment or files.
- Structured logging configuration.
- Request ID forwarding rules.
- Liveness and readiness endpoints.
- Startup failure simulation.
- Graceful shutdown and bounded cleanup.
- Reverse proxy example.
- Containerfile and Kubernetes manifest example.
- Production testing strategy.
- Deployment checklist.

Reference applications must remain small enough to audit. They demonstrate
framework composition, not a complete business product.

## 12. Recipes

Recipes solve one concrete problem and may reuse reference-application code.

| Recipe | Required outcome |
| --- | --- |
| Repository provider | Interface token, implementation, test replacement |
| Request transaction | Request-owned async context manager and cleanup |
| Authorization guard | Policy provider plus 403 mapping |
| Custom validation pipe | Domain-specific conversion and structured errors |
| Domain exception filter | Stable Problem Details mapping |
| External HTTP client | Singleton client resource and shutdown |
| Multiple settings modules | Dynamic keys and explicit visibility |
| Startup failure testing | Prove no resources/hooks remain active |
| Background work | Explain why request dependencies must not escape scope |
| Correlated logging | Bind application/module/provider/request fields |
| Feature module testing | Override only exported providers |
| Driver response escape hatch | Explicit portability warning |

## 13. API Reference Plan

API reference must cover documented public symbols grouped by owning facade.

### 13.1 `tori_py`

- Driver-neutral NestApplication, adapter/binder/runtime protocols, and compiled
  graph identities.
- Module decorators and metadata.
- Provider declarations and scopes.
- Tokens and `Inject`.
- Controller and route decorators.
- Binding markers.
- Pipeline decorators, protocols, and PipelineOptions.
- Application lifecycle options.
- Public errors and diagnostics.

### 13.2 `tori_py.settings`

- SettingsModule and SettingsOptions.
- Secret and SecretMarker.
- BootstrapContext.
- Codec and SettingsDecoder implementations.
- Loading and secret-path helpers intended as public API.

### 13.3 `tori_py.http`

- HttpContext and current HTTP context access.
- HttpException.
- MsgspecValidationPipe.
- Framework-owned HTTP route and pipeline semantics.

### 13.4 `tori_py.starlette`

- StarletteAdapter and transport-only StarletteOptions.
- ASGI wrapper.
- Native RequestContext view.
- Driver-specific escape hatches.

### 13.5 `tori_py.testing`

- TestingModule.
- ProviderOverride.
- TestingApplication.
- Module identity forms.

### 13.6 `tori_py.cli`

- Console command syntax only.
- Internal parser/loader helpers are not public API documentation.

Before API generation, review `__all__` for each facade and ensure every public
symbol has a useful docstring and stable ownership.

## 14. Execution Phases

### D0: Baseline and inventory

Entry criteria:

- ToriPy N0-N6 tests pass.
- Current examples boot successfully.

Tasks:

1. Run all existing quality gates.
2. Export public symbols from `tori_py`, `tori_py.settings`, `tori_py.starlette`, and
   `tori_py.testing` into an inventory document.
3. Map each public symbol to architecture/spec sections.
4. Mark internal symbols accidentally exported or public symbols missing from
   facades.
5. Inventory current examples and docs tests.
6. Record behavior gaps discovered while running examples.
7. Freeze canonical terminology from section 9.3.
8. Create a page-to-test traceability table.

Artifacts:

- `docs/contributing/public-api-inventory.md`
- `docs/contributing/traceability.md`
- Initial issue/task list for behavior mismatches.

Exit criteria:

- Every public symbol has an owner and planned documentation location.
- No unresolved behavior contradiction blocks Getting Started.

### D1: Documentation tooling and CI

Entry criteria:

- D0 inventory is complete.

Tasks:

1. Add the root `docs` dependency group using `uv`.
2. Add `mkdocs.yml` with strict navigation.
3. Add Material, mkdocstrings, and snippet configuration.
4. Create only the D1/D2 pages needed for a strict initial build; add later
   guide directories with the phase that owns their content.
5. Add a minimal home page and 404 page.
6. Add `packages/tori-py/scripts/verify_docs.py`.
7. Make `verify_docs.py` check documented imports and required files.
8. Add a strict MkDocs build command to CI documentation.
9. Add docs test discovery to the normal test suite.
10. Verify that docs tooling is absent from package runtime metadata.

Verification:

```text
uv lock --check
uv sync --locked --group docs
uv run --group docs mkdocs build --strict
uv run pytest packages/tori-py/tests/docs
uv run python packages/tori-py/scripts/verify_docs.py
```

Exit criteria:

- Empty/placeholder-free strict site build passes.
- Documentation dependencies remain development-only.

### D2: Home and Getting Started

Entry criteria:

- D1 site and tests are operational.

Tasks:

1. Write Home with a precise v1 value proposition.
2. Write Why ToriPy without claiming feature parity with NestJS.
3. Write Installation for base, `settings-yaml`, and `cli` extras.
4. Write First Application from an empty directory.
5. Write Project Structure.
6. Write First Controller.
7. Write First Provider.
8. Write minimal Settings configuration.
9. Write first TestingModule test.
10. Write Next Steps with audience-specific paths.
11. Create and test E001-E008.
12. Test every shell command on Windows-compatible and shell-neutral paths where
    possible.

Exit criteria:

- A reader can install, run, request, test, and stop an application by following
  only Getting Started.
- All E001-E008 examples pass.

### D3: Fundamentals

Entry criteria:

- D2 learning path passes from a clean environment.

Tasks:

1. Write Modules, Dynamic Modules, and Global Modules.
2. Write Providers and Provider Tokens.
3. Write constructor injection and explicit Inject behavior.
4. Write module visibility and ambiguity rules.
5. Write scopes with an ownership table.
6. Write managed resources and LIFO cleanup.
7. Write lifecycle hook order.
8. Write startup rollback and bounded shutdown.
9. Add failure diagnostics to relevant pages.
10. Create and test E009-E044.

Exit criteria:

- All DI, visibility, scope, and lifecycle contracts are user-documented.
- E009-E044 pass without private imports.

### D4: HTTP guide

Entry criteria:

- Fundamentals are complete.

Tasks:

1. Write Controllers and Routes.
2. Document exact path-join and duplicate rules.
3. Write raw binding overview.
4. Write one page per binding marker.
5. Explain default values and missing input.
6. Write RequestContext and provider injection.
7. Write response encoding and explicit response ownership.
8. Write Problem Details and request IDs.
9. Write body streaming limit and JSON media rules.
10. Write route ordering and trailing slash behavior.
11. Write Starlette escape hatch limitations.
12. Create and test E045-E071.

Exit criteria:

- Every N4 public behavior has a guide and executable example.
- Examples do not imply automatic type conversion.

### D5: Pipeline and validation

Entry criteria:

- D4 raw binding documentation is complete.

Tasks:

1. Write the exact pipeline execution diagram.
2. Write middleware nesting and one-shot `next` behavior.
3. Write guards and 403 mapping.
4. Write pipes and ArgumentMetadata.
5. Write MsgspecValidationPipe for body/scalar/repeated values.
6. Write interceptors and unwind order.
7. Write filter precedence and fallthrough.
8. Write cancellation and BaseException rules.
9. Write response-transmission safety.
10. Explain root-qualified global providers.
11. Create and test E072-E094.

Exit criteria:

- The full N5 order is documented and tested.
- Cancellation examples prove filters cannot swallow cancellation.

### D6: Settings and observability

Entry criteria:

- D5 is complete.

Tasks:

1. Write Settings overview and source configuration.
2. Write one page for files, dotenv, environment, and precedence.
3. Write nested merge behavior.
4. Write custom codec and decoder extension points.
5. Write Secret metadata and redaction rules.
6. Write CLI override rules and secret rejection.
7. Write default logger and structured fields.
8. Write request correlation and reserved-field ownership.
9. Write failure diagnostics without exposing values.
10. Create and test E095-E116.

Exit criteria:

- Every settings source and precedence rule has an executable example.
- Secret examples assert that raw secret values do not appear in errors/logs.

### D7: Testing guide

Entry criteria:

- User-facing runtime concepts are documented.

Tasks:

1. Write TestingModule workflow.
2. Write value/class/factory/alias overrides.
3. Write global and module-targeted overrides.
4. Write static and dynamic module identities.
5. Write descriptor replacement before materialization.
6. Write ASGI request testing.
7. Write resource and lifecycle assertions.
8. Write startup failure tests.
9. Write override security boundaries.
10. Create and test E117-E130.

Exit criteria:

- Every supported override form has one executable example.
- No guide suggests private-provider override shortcuts.

### D8: CLI, deployment, and security

Entry criteria:

- D2-D7 core guides are complete.

Tasks:

1. Write CLI installation and `tori-py run` command.
2. Write async factory loading and BootstrapContext behavior.
3. Write direct ASGI deployment.
4. Write Uvicorn deployment.
5. Write reverse proxy request ID rules.
6. Write container deployment.
7. Write Kubernetes probes and termination guidance.
8. Write health/readiness guidance without inventing framework APIs.
9. Write graceful shutdown operational behavior.
10. Write security pages for secrets, input limits, errors, IDs, and
    cancellation.
11. Create and test E131-E142.

Exit criteria:

- CLI and deployment commands are executable.
- Security claims have matching behavioral tests.

### D9: Recipes and reference applications

Entry criteria:

- All concept guides are complete.

A foundation reference application MAY be implemented earlier as a code-first
discovery slice when it has its own executable tests and does not claim that the
surrounding user guides already exist. Its documentation integration, recipe
links, and release review remain D9 work.

Tasks:

1. Implement and test all recipes from section 12.
2. Build Task API.
3. Build Community API Skeleton.
4. Build Production Blueprint.
5. Cross-link recipes from concept guides.
6. Cross-link reference applications from Getting Started Next Steps.
7. Add architecture diagrams for each reference application.
8. Add failure-mode tests to each reference application.
9. Run all reference applications through production lifespan.

Exit criteria:

- Three reference applications boot, serve requests, and shut down cleanly.
- Each combines modules, settings, pipeline, testing, and lifecycle behavior.

### D10: API reference and release review

Entry criteria:

- D2-D9 content is complete.

Tasks:

1. Review every public `__all__` facade.
2. Add or improve public docstrings.
3. Generate API reference pages.
4. Verify every guide API link resolves.
5. Run artifact verification from wheel and sdist.
6. Run all atomic and reference examples.
7. Run strict site build.
8. Run a technical correctness review against architecture/specs.
9. Run a security-focused documentation review.
10. Run a new-user walkthrough from an empty directory.
11. Run a NestJS-user terminology review.
12. Record residual v1 limitations.

Verification:

```text
uv lock --check
uv sync --locked --group docs
uv run pytest
uv run pytest packages/tori-py/tests/docs examples/tori_py
uv run ruff check .
uv run ruff format --check .
uv run ty check packages/tori-py-cqrs-core/src packages/tori-py-cqrs-core/tests packages/tori-py-cqrs-fastapi/src packages/tori-py-cqrs-fastapi/tests packages/tori-py/src packages/tori-py/tests examples/tori_py packages/tori-py/scripts
uv run --group docs mkdocs build --strict
uv build --package tori-py
uv run python packages/tori-py/scripts/verify_artifacts.py dist/
uv run python packages/tori-py/scripts/verify_docs.py
```

Exit criteria:

- Definition of Done in section 2 is satisfied.
- Independent review has no required findings.

## 15. Delivery Waves for Examples

Creating 142 examples in one change is prohibited. Deliver them in reviewable
waves:

| Wave | Examples | Theme |
| --- | --- | --- |
| W1 | E001-E008 | Getting Started |
| W2 | E009-E030 | Modules and providers |
| W3 | E031-E044 | Scopes and lifecycle |
| W4 | E045-E058 | Core HTTP binding and responses |
| W5 | E059-E071 | HTTP errors, ordering, escape hatches |
| W6 | E072-E085 | Pipeline ordering and validation |
| W7 | E086-E094 | Filters, cancellation, transmission safety |
| W8 | E095-E110 | Settings and secrets |
| W9 | E111-E130 | Logging and testing |
| W10 | E131-E142 | CLI and operations |

Each wave requires:

1. Guide pages using the examples.
2. Focused example tests.
3. Full repository tests.
4. Strict docs build.
5. Review before commit.

## 16. Commit Strategy

Use small, independently valid commits:

```text
Add ToriPy documentation tooling
Write ToriPy Getting Started guide
Document ToriPy modules and providers
Add ToriPy module and provider examples
Document ToriPy scopes and lifecycle
Add ToriPy lifecycle examples
Document ToriPy HTTP bindings
Add ToriPy HTTP examples
Document ToriPy pipeline execution
Add ToriPy pipeline examples
Document ToriPy settings and observability
Add ToriPy settings examples
Document ToriPy testing APIs
Add ToriPy testing examples
Document ToriPy CLI and deployment
Add ToriPy operational examples
Add ToriPy Task API reference application
Add ToriPy Community API reference application
Add ToriPy production blueprint
Generate and review ToriPy API reference
Harden ToriPy documentation release gates
```

Do not combine tooling, 20 examples, all guides, and generated API reference in
one commit.

## 17. Traceability Requirements

Maintain a table at `docs/contributing/traceability.md` with these columns:

| Contract | Guide | Example | Test | Status |
| --- | --- | --- | --- | --- |
| Module exports | Fundamentals / Modules | E010 | test path | Complete |

Trace at least:

- Every cross-phase invariant in `spec/tori-py/README.md`.
- Every public facade symbol.
- Every N4 HTTP binding.
- Every N5 pipeline stage.
- Every settings source and secret rule.
- Every TestingModule override form.
- CLI factory and override behavior.
- Every documented failure diagnostic.

## 18. Automation Requirements

### 18.1 Documentation verifier

`verify_docs.py` must fail when:

- A required guide file is missing.
- Navigation references a missing page.
- A documented public import cannot be imported.
- An example directory lacks README or test coverage.
- An example uses a private ToriPy import without an allowlist reason.
- A runnable snippet source file is missing.
- The example catalog references an unknown directory.

### 18.2 Example test policy

- Atomic examples are collected by pytest.
- Server examples use bounded startup and shutdown.
- No test leaves ports, tasks, resources, or subprocesses active.
- Network access is not required for normal example tests.
- Optional extras use isolated tests or explicit skip reasons.
- Failure examples assert diagnostic code and redaction, not fragile complete
  message text.

### 18.3 Link and navigation policy

- Strict MkDocs build is required.
- No broken internal links.
- External links are centralized where practical.
- Guide renames update navigation and traceability in the same commit.

## 19. Review Checklists

### 19.1 Technical review

- Claims match architecture and executable specs.
- Public imports exist in built artifacts.
- Lifecycle order is exact.
- Scope ownership is exact.
- Raw binding versus validation is not blurred.
- Pipeline order is exact.
- Cancellation is never documented as filterable.
- Secret and request ID rules are exact.
- Testing override boundaries are exact.
- No deferred feature is presented as implemented.

### 19.2 Writing review

- Page answers one primary user question.
- First paragraph states purpose.
- Minimal example appears before advanced discussion.
- Terms are consistent.
- Headings support scanning.
- Examples show expected output.
- Errors include recovery guidance.
- Links lead to the next likely task.
- No phase implementation language leaks into user guides.

### 19.3 Security review

- No real credentials or realistic secrets are committed.
- Error examples do not expose tracebacks to clients.
- CLI secret rejection does not echo values.
- Request IDs are never presented as authentication data.
- Body limits are documented for streaming input.
- Cancellation and stale resolvers fail closed.
- Driver-specific background behavior includes scope warnings.

## 20. Progress Tracking

Update this table after every documentation phase:

| Phase | Status | Primary output |
| --- | --- | --- |
| D0 | In progress | Inventory and traceability |
| D1 | In progress | MkDocs and CI foundation |
| D2 | In progress | Getting Started |
| D3 | Pending | Fundamentals |
| D4 | Pending | HTTP guide |
| D5 | Pending | Pipeline guide |
| D6 | Pending | Settings and observability |
| D7 | Pending | Testing guide |
| D8 | Pending | CLI, deployment, security |
| D9 | In progress | Task API foundation reference application |
| D10 | Pending | API reference and release review |

Allowed status values:

```text
Pending
In progress
Blocked: <reason>
Complete: <commit>
```

## 21. Risks and Controls

| Risk | Control |
| --- | --- |
| Documentation diverges from code | Executable snippets and traceability |
| Too many low-value examples | Atomic purpose and wave review |
| Examples duplicate framework tests | Examples test public workflows, unit tests test internals |
| Tooling enters runtime dependencies | Separate docs dependency group and metadata test |
| NestJS terminology implies false parity | Concepts map plus Python-specific differences |
| Reference applications become product code | In-memory boundaries and explicit scope limits |
| Private APIs leak into guides | Automated private-import scan |
| Optional extras break base imports | Isolated import and artifact tests |
| Copy-paste snippets rot | Include from tested files |
| Operational guides overpromise | Validate commands and label environment assumptions |

## 22. Immediate Next Actions

Execute these actions in order:

1. Approve MkDocs Material as the documentation generator.
2. Start D0 and create the public API inventory.
3. Create the architecture/spec-to-guide traceability table.
4. Resolve any public facade inconsistencies discovered by the inventory.
5. Implement D1 tooling in one commit.
6. Implement D2 Getting Started with E001-E008.
7. Run a clean-environment walkthrough before starting Fundamentals.

Do not start bulk example generation before D0-D2 establish the content,
testing, and navigation conventions all later examples must follow.
