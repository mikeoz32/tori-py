# Public API Inventory

This inventory freezes the public surface examined for D0. The owning facade is
the supported import location; implementation modules are not documentation
targets. Symbol groups map to the planned API-reference pages in
`TORI_PY_DOCUMENTATION_PLAN.md` section 13.

## `tori_py`

| Symbols | Owner | Planned location | Source contract |
| --- | --- | --- | --- |
| `NestApplication`, `ApplicationAdapter`, `ApplicationBinder`, `ApplicationRuntime`, `NoopApplicationAdapter` | `tori_py.application` | Application Lifecycle and Adapters | N2-N4 |
| `module`, `ModuleMetadata`, `ModuleSpec`, `ModuleImport`, `ModuleProvider`, `ModuleFactory`, `DeferredModule`, `get_module_metadata` | `tori_py.core.modules` | Modules and Dynamic Modules | N1 |
| `compile_graph`, `CompiledGraph`, `GraphShape`, `ModuleId`, `ModulePlan`, `ProviderRef`, `ProviderPlan`, `DependencyPlan` | `tori_py.core.compiler` | Compiled Application Graph | N1 |
| `ValueProvider`, `ClassProvider`, `FactoryProvider`, `AliasProvider`, `ProviderDeclaration`, `ProviderFactory`, `Token`, `Scope`, `Inject`, `injectable`, `get_injectable_metadata`, `provider_token`, `normalize_scope`, `validate_token` | `tori_py.core.providers` | Providers, Tokens, Dependency Injection, Scopes | N1-N2 |
| `controller`, `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `route`, `status`, `get_controller_metadata`, `get_route_metadata`, `get_status_metadata` | `tori_py.core.metadata` | Controllers and Routes | N4 |
| `Body`, `Path`, `Query`, `Header`, `Cookie`, `Context`, `RouteMetadata`, `ControllerMetadata`, `StatusMetadata` | `tori_py.core.metadata` | HTTP Binding | N4 |
| `websocket_gateway`, `Socket`, `WebSocketGatewayMetadata`, `get_websocket_gateway_metadata`, `WebSocketContext`, `current_websocket_context` | `tori_py.core.metadata` and `tori_py.websocket.context` | WebSocket Gateways and Context | N9 |
| `middleware`, `guards`, `pipes`, `interceptors`, `filters`, `use_middleware`, `use_guard`, `use_guards`, `use_pipe`, `use_pipes`, `use_interceptor`, `use_interceptors`, `use_filter`, `use_filters`, `get_pipeline_metadata` | `tori_py.core.metadata` | Pipeline | N5 |
| `Guard`, `Pipe`, `Interceptor`, `ExceptionFilter`, `Middleware`, `ExecutionContext`, `ArgumentMetadata`, `PipelineResult`, `ScopedResolver`, `WorkScopeFactory`, `ShutdownContext`, `Logger`, `Codec`, `SettingsDecoder` | `tori_py.core.protocols` | Pipeline, Settings, Scopes, Lifecycle, Observability | N2-N5 |
| `ApplicationOptions`, `PipelineOptions`, `ApplicationState`, `RequestScope` | `tori_py.core.options` and `tori_py.core.runtime` | Application Lifecycle and Global Pipeline | N2-N5 |
| `MetadataKey`, `MetadataDecorator`, `metadata`, `Reflector` | `tori_py.core.reflection` | Typed Reflection Metadata | N7 |
| `ProviderView`, `ModuleView` | `tori_py.core.discovery` | Compiled Provider Discovery | N7 |
| `ModulesContainer`, `DiscoveryService` | `tori_py.core.protocols` | Discovery Service Contracts | N7 |
| `ToriPyError`, `BootstrapError`, `ApplicationStateError`, `LifecycleError`, `PipelineStateError`, `ResolutionError`, `ResourceError`, `ScopeError`, `ScopeClosedError`, `SettingsError`, `Diagnostic`, `DiagnosticCode`, `DIAGNOSTIC_CODES` | `tori_py.core.errors` | Failure Diagnostics and Problem Details | N1-N5 |

## `tori_py.settings`

| Symbols | Owner | Planned location | Source contract |
| --- | --- | --- | --- |
| `SettingsModule`, `SettingsOptions`, `load_settings`, `SETTINGS_TOKEN` | `tori_py.settings.runtime` | Settings Overview and Configuration | N3 |
| `MsgspecCodec`, `MsgspecSettingsDecoder`, `Secret`, `SecretMarker`, `secret_paths` | `tori_py.settings.runtime` | Custom Codecs and Secrets | N3 |
| `BootstrapContext`, `current_bootstrap_context`, `use_bootstrap_context` | `tori_py.settings.context` | CLI Overrides and Testing | N3, N6 |
| `Codec`, `SettingsDecoder` | re-exported from `tori_py.core.protocols` | Custom Codecs | N3 |

## `tori_py.http`

| Symbols | Owner | Planned location | Source contract |
| --- | --- | --- | --- |
| `HttpContext`, `current_http_context` | `tori_py.http.context` | HTTP Execution Context | N4-N5 |
| `HttpException` | `tori_py.http.errors` | Problem Details | N4-N5 |
| `HttpResponse`, `ResponseHeaderMetadata`, `get_response_header_metadata`, `header` | `tori_py.http.response` | Portable Explicit HTTP Responses | N4 |
| `MsgspecValidationPipe` | `tori_py.http.validation` | Msgspec Validation | N5 |
| `HttpPipelineAdapter`, `PipelineExecutor`, `ParameterPlan`, `RoutePlan`, `compile_controller_routes`, `compile_routes`, `bind_routes` | `tori_py.http.pipeline` and `tori_py.http.routes` | HTTP Adapter Extension Contracts | N4-N5 |

## `tori_py.starlette`

| Symbols | Owner | Planned location | Source contract |
| --- | --- | --- | --- |
| `StarletteAdapter`, `ASGIApplication`, `asgi` | `tori_py.starlette.application` | ASGI and Deployment | N4 |
| `StarletteOptions` | `tori_py.starlette.options` | Starlette Transport Configuration | N4 |
| `RequestContext`, `current_request_context` | `tori_py.starlette.context` | Native Starlette Context View | N4 |
| `WebSocketRequestContext` | `tori_py.starlette.websockets` | Native Starlette WebSocket Context View | N9 |
| `problem_response` | `tori_py.starlette.errors` | Problem Details Rendering | N4-N5 |

## `tori_py.websocket`

| Symbols | Owner | Planned location | Source contract |
| --- | --- | --- | --- |
| `WebSocketContext`, `current_websocket_context` | `tori_py.websocket.context` | WebSocket Connection Context | N9 |
| `WebSocketParameterPlan`, `WebSocketPlan`, `compile_websocket_gateway`, `compile_websocket_routes`, `bind_websocket_routes` | `tori_py.websocket.routes` | WebSocket Adapter Extension Contracts | N9 |
| `WebSocketPipelineAdapter`, `WebSocketPipelineExecutor`, `WebSocketForbidden` | `tori_py.websocket.pipeline` and `tori_py.websocket.errors` | WebSocket Execution Pipeline | N9 |

## `tori_py.testing` and CLI

| Symbols | Owner | Planned location | Source contract |
| --- | --- | --- | --- |
| `TestingModule`, `TestingApplication`, `ProviderOverride`, `http_client` | `tori_py.testing` | Testing and HTTPX Client | N3-N4 |
| `tori-py run` | `tori_py.cli:main` console command | CLI Run | N6 |

`tori_py` re-exports framework-agnostic core declarations, the driver-neutral
application facade, the portable HTTP response API, and the driver-neutral
WebSocket declaration/context API. Starlette, settings, and testing APIs require
their named public subpackage.
`tori_py.cli` exposes the console entry point only; parser and loader helpers are
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
