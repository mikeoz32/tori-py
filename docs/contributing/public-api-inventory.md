# Public API Inventory

This inventory freezes the public surface examined for D0. The owning facade is
the supported import location; implementation modules are not documentation
targets. Symbol groups map to the planned API-reference pages in
`NESTPY_DOCUMENTATION_PLAN.md` section 13.

## `nestpy`

| Symbols | Owner | Planned location | Source contract |
| --- | --- | --- | --- |
| `NestApplication`, `ApplicationAdapter`, `ApplicationBinder`, `ApplicationRuntime`, `NoopApplicationAdapter` | `nestpy.application` | Application Lifecycle and Adapters | N2-N4 |
| `module`, `ModuleMetadata`, `ModuleSpec`, `ModuleImport`, `ModuleFactory`, `DeferredModule`, `get_module_metadata` | `nestpy.core.modules` | Modules and Dynamic Modules | N1 |
| `compile_graph`, `CompiledGraph`, `GraphShape`, `ModuleId`, `ModulePlan`, `ProviderRef`, `ProviderPlan`, `DependencyPlan` | `nestpy.core.compiler` | Compiled Application Graph | N1 |
| `ValueProvider`, `ClassProvider`, `FactoryProvider`, `AliasProvider`, `ProviderDeclaration`, `ProviderFactory`, `Token`, `Scope`, `Inject`, `provider_token`, `normalize_scope`, `validate_token` | `nestpy.core.providers` | Providers, Tokens, Dependency Injection, Scopes | N1-N2 |
| `controller`, `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `route`, `status`, `get_controller_metadata`, `get_route_metadata`, `get_status_metadata` | `nestpy.core.metadata` | Controllers and Routes | N4 |
| `Body`, `Path`, `Query`, `Header`, `Cookie`, `Context`, `RouteMetadata`, `ControllerMetadata`, `StatusMetadata` | `nestpy.core.metadata` | HTTP Binding | N4 |
| `middleware`, `guards`, `pipes`, `interceptors`, `filters`, `use_middleware`, `use_guard`, `use_guards`, `use_pipe`, `use_pipes`, `use_interceptor`, `use_interceptors`, `use_filter`, `use_filters`, `get_pipeline_metadata` | `nestpy.core.metadata` | Pipeline | N5 |
| `Guard`, `Pipe`, `Interceptor`, `ExceptionFilter`, `Middleware`, `ExecutionContext`, `ArgumentMetadata`, `PipelineResult`, `ScopedResolver`, `Logger`, `Codec`, `SettingsDecoder` | `nestpy.core.protocols` | Pipeline, Settings, Observability | N2-N5 |
| `ApplicationOptions`, `PipelineOptions`, `ApplicationState`, `RequestScope` | `nestpy.core.options` and `nestpy.core.runtime` | Application Lifecycle and Global Pipeline | N2-N5 |
| `NestpyError`, `BootstrapError`, `ApplicationStateError`, `LifecycleError`, `PipelineStateError`, `ResolutionError`, `ResourceError`, `ScopeError`, `ScopeClosedError`, `SettingsError`, `Diagnostic`, `DiagnosticCode`, `DIAGNOSTIC_CODES` | `nestpy.core.errors` | Failure Diagnostics and Problem Details | N1-N5 |

## `nestpy.settings`

| Symbols | Owner | Planned location | Source contract |
| --- | --- | --- | --- |
| `SettingsModule`, `SettingsOptions`, `load_settings`, `SETTINGS_TOKEN` | `nestpy.settings.runtime` | Settings Overview and Configuration | N3 |
| `MsgspecCodec`, `MsgspecSettingsDecoder`, `Secret`, `SecretMarker`, `secret_paths` | `nestpy.settings.runtime` | Custom Codecs and Secrets | N3 |
| `BootstrapContext`, `current_bootstrap_context`, `use_bootstrap_context` | `nestpy.settings.context` | CLI Overrides and Testing | N3, N6 |
| `Codec`, `SettingsDecoder` | re-exported from `nestpy.core.protocols` | Custom Codecs | N3 |

## `nestpy.http`

| Symbols | Owner | Planned location | Source contract |
| --- | --- | --- | --- |
| `HttpContext`, `current_http_context` | `nestpy.http.context` | HTTP Execution Context | N4-N5 |
| `HttpException` | `nestpy.http.errors` | Problem Details | N4-N5 |
| `MsgspecValidationPipe` | `nestpy.http.validation` | Msgspec Validation | N5 |
| `HttpPipelineAdapter`, `PipelineExecutor`, `ParameterPlan`, `RoutePlan`, `compile_routes`, `bind_routes` | `nestpy.http.pipeline` and `nestpy.http.routes` | HTTP Adapter Extension Contracts | N4-N5 |

## `nestpy.starlette`

| Symbols | Owner | Planned location | Source contract |
| --- | --- | --- | --- |
| `StarletteAdapter`, `ASGIApplication`, `asgi` | `nestpy.starlette.application` | ASGI and Deployment | N4 |
| `StarletteOptions` | `nestpy.starlette.options` | Starlette Transport Configuration | N4 |
| `RequestContext`, `current_request_context` | `nestpy.starlette.context` | Native Starlette Context View | N4 |

## `nestpy.testing` and CLI

| Symbols | Owner | Planned location | Source contract |
| --- | --- | --- | --- |
| `TestingModule`, `TestingApplication`, `ProviderOverride` | `nestpy.testing.runtime` | Testing | N3 |
| `nestpy run` | `nestpy.cli:main` console command | CLI Run | N6 |

`nestpy` re-exports framework-agnostic core declarations and the driver-neutral
application facade. Starlette, settings, and testing APIs require their named
public subpackage.
`nestpy.cli` exposes the console entry point only; parser and loader helpers are
internal despite being module-level implementation names.

Guard, pipe, interceptor, and filter decorators accept a provider token, an
implementation class, or a preconstructed protocol instance. Classes are
module-owned providers with DI and lifecycle support unless an explicit visible
provider already owns the class token. Instances are shared and externally
owned. Middleware remains provider-token based. `NestApplication` also exposes
`use_global_guard()`, `use_global_pipe()`, `use_global_interceptor()`, and
`use_global_filter()` for externally owned instances or already-visible DI
tokens added by an application factory before ASGI lifespan startup.
Registered class tokens retain DI ownership; unregistered enhancer classes must
be present in the compile-time `PipelineOptions` snapshot.

## Canonical terminology

Use **provider declaration**, **provider token**, **module visibility**,
**request scope**, **managed resource**, **application factory**, **raw
binding**, **Problem Details**, **request ID**, and **dynamic module identity**.
The terminology table in plan section 9.3 defines terms to avoid.
