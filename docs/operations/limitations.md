# Limitations

This matrix describes the current `tori-py-framework` v1/beta boundary. The
repository also contains independently installable packages for selected CQRS,
event-sourcing, SQLAlchemy, OpenAPI, microservice, and persistent-stream use
cases. Their presence does not turn those features into core framework APIs or
remove their own documented limitations.

## Platform And Hosting

| Area | Current boundary | Consequence or alternative |
| --- | --- | --- |
| Python | Requires `>=3.14,<3.15` | Other Python versions are unsupported. |
| Release maturity | Package metadata is beta and the initial line is `0.x` | Pin versions and review changelogs; compatibility may evolve by minor release. |
| HTTP driver | Starlette is the sole v1 HTTP driver | Driver-specific responses and behavior are not portable to a future adapter. |
| ASGI server | Core exports ASGI; the CLI extra uses Uvicorn | Other ASGI servers are not the tested CLI path and must correctly drive lifespan. |
| Lifespan | Required; the wrapper starts once and cannot restart | Every worker/reload must import a fresh wrapper and application. Lifespan-off hosting leaves HTTP at 503. |
| CLI | Only `run module:factory` plus repeated non-secret `--set` | No host, port, reload, worker, proxy, TLS, timeout, or logging flags; run Uvicorn directly. |
| Server supervision | Not provided | Use the container platform, process manager, or orchestrator. |
| Multi-process state | Each worker has independent singletons and memory | Use external state and include all workers in capacity calculations. |
| Health endpoints | Not provided | Implement normal controllers and application-owned liveness/readiness policy. |
| Deployment prefix | No ToriPy root-path or proxy-prefix API | Configure and test proxy, Uvicorn, and Starlette behavior directly. |

## Composition And Dependency Injection

| Area | Current boundary | Consequence or alternative |
| --- | --- | --- |
| Registration | Explicit modules/providers/controllers only | An annotation never auto-registers a class. Compile-time guard, pipe, interceptor, and filter class registrations can synthesize their own class provider; middleware still requires an explicit provider. There is no package scanning or process-global registry. |
| Tokens | Class and string tokens | No arbitrary object-token model. |
| Exports | Not automatically transitive | Re-export imported tokens explicitly. |
| Visibility conflicts | Ambiguity is an error; registration order is not a fallback | Resolve module ownership instead of relying on last registration. |
| Injection | Constructor/factory parameters only, through annotations or `Inject` | No property, field, or runtime service-locator injection. |
| Implicit classes | Unregistered annotated dependencies are not created | Declare `@injectable()` shorthand or an explicit provider. The only pipeline exception is a directly registered guard, pipe, interceptor, or filter implementation class compiled into an implicit class provider; middleware has no fallback. |
| Module instances | Constructed with no arguments | Modules receive no constructor DI; put behavior in providers. |
| Scopes | Singleton, request, and transient only | No custom user-defined scope type. Explicit work scopes reuse request-scope semantics for non-HTTP work. |
| Scope paths | A singleton cannot depend on a request provider, including through transients | Inject `WorkScopeFactory` and open bounded work instead. |
| Controllers | Eager singleton only | Request/transient controller scopes are invalid; inject request providers into route parameters or pipeline components. |
| Dynamic modules | Identity is `(module class, key)` and descriptors are explicit | No configuration hashing or automatic descriptor deduplication. |
| Discovery | Compiled graph only | No import-package scanning or runtime registration. |
| Runtime mutation | Graph and route registrations are fixed after compilation | Create a new application for composition changes. |
| Production resolving | `NestApplication` has no public general-purpose resolver facade | Express startup/runtime work as lifecycle-managed providers; testing has a deliberate resolver facade. |

## Resources And Lifecycle

| Area | Current boundary | Consequence or alternative |
| --- | --- | --- |
| Managed protocol | Python sync/async context managers | Other cleanup conventions need an application wrapper. |
| Value ownership | `ValueProvider` is unmanaged unless `manage=True` | The caller that supplied the value retains ownership and must coordinate its lifecycle by default. |
| Sync resources | Enter/exit is offloaded to a framework executor | Thread affinity is not guaranteed; use an application-provided async wrapper for thread-affine resources. |
| Cancellation | Cannot forcibly stop non-cooperative coroutines or executor threads | Shutdown logs lingering work and returns at its deadline. Design external operations for interruption. |
| Shutdown | One bounded best-effort deadline | No unbounded second cleanup path after timeout. Outer process grace must be longer. |
| Background work | No built-in job queue or general detached-task manager | Use explicit integrations and `WorkScopeFactory`; do not retain request scopes. |
| Cross-process lifecycle | Hooks run once per application process | One-time deployment tasks and migrations must live outside replicated startup unless concurrency-safe. |

## HTTP And Routing

| Area | Current boundary | Consequence or alternative |
| --- | --- | --- |
| Protocols | HTTP only | No first-class WebSocket API. |
| Templates/static files | No framework APIs | Serve at the edge or use an explicitly Starlette-specific integration. |
| Parsed body | JSON media types only for `Body()` | No framework-managed form, multipart, or file-upload binding. |
| Raw request streaming | One `BodyStream(max_bytes=...)`, single consumer, request lifetime | No parsing or spooling; it must consume through EOF before successful response and cannot escape into response/background work. |
| Response streaming/files/background | No portable framework API | Native Starlette `Response` subclasses are an escape hatch without future-driver portability. |
| Type conversion | Bindings are raw | Register `MsgspecValidationPipe` or a custom pipe; annotations alone do not convert inputs. |
| Parameter inference | Every parameter needs an explicit binding or `Inject` marker | Names do not imply path/query/header/body sources. |
| Body consumption | One body-consuming binding per route | `Body()` and `BodyStream()` cannot be combined. |
| Global body limit | `StarletteOptions.body_size_limit` applies to parsed JSON and `@no_body`, not every route | Use `BodyStream` limits where selected and enforce total request limits at the proxy/server. |
| Content length | Limits use actual ASGI bytes, not `Content-Length` | The framework does not reject solely from the declared length. |
| Header/query limits | No framework count, size, or complexity limits | Configure edge/server limits and application validation. |
| Router semantics | ToriPy rejects exact duplicates, then delegates matching to Starlette | Overlaps, converters, declaration precedence, redirects, implicit HEAD/OPTIONS, and `Allow` follow the pinned Starlette version. |
| Trailing slash | `/x` and `/x/` are distinct at ToriPy duplicate validation | Starlette may redirect according to its routing behavior. |
| Runtime routes | No route mutation after compilation | Restart with a newly compiled graph. |
| Portable responses | `HttpResponse` supports bytes, status, and headers | Advanced Starlette response behavior is driver-specific. |
| Response schemas | Core runtime does not enforce response schemas | Validate in application code; OpenAPI is an independent optional package and documentation is not runtime enforcement. |

## Security And Observability

| Area | Current boundary | Consequence or alternative |
| --- | --- | --- |
| Authentication | Not implemented | Supply an identity integration and guards. |
| Authorization | Guard extension point only | Application policy must cover route and object-level decisions. |
| Browser/network policy | No CORS, CSRF, host validation, rate limiting, TLS, or security-header policy | Configure explicit application or edge controls. |
| Proxy headers | ToriPy does not interpret forwarded headers | Configure Uvicorn trust and strip untrusted values at the proxy. |
| Request ID | Syntax-validated correlation metadata only | Safe IDs can still be attacker-selected; never use them as identity or idempotency keys. |
| Secret annotation | Redaction/CLI policy metadata only | No encryption, secret-store client, rotation, or prevention of application disclosure. |
| Error disclosure | Default Problem Details hides unexpected exception details | Custom filters, native responses, proxy pages, and application logging remain application responsibility. |
| Logger output | `PythonLogger` adds `record.tori_py` | No handler, JSON formatter, rotation, retention, or log shipping is installed. |
| Automatic fields | Request-level application/request ID/scope correlation | Do not assume every log has route, module, provider, or resource state. |
| Telemetry | No OpenTelemetry dependency, tracing backend, metrics endpoint, or profiler | Add explicit integrations and define their lifecycle/cardinality policy. |
| Access logs | Owned by the ASGI server | Configure and redact Uvicorn/proxy access logs separately. |

## Settings

| Area | Current boundary | Consequence or alternative |
| --- | --- | --- |
| Discovery | Sources must be explicitly listed | No automatic `.env`, profile, or config-directory scan. |
| Formats | TOML, JSON, optional safe YAML, and narrow dotenv | Other formats require application parsing or a different source layer. A custom codec does not replace file parsers. |
| YAML | Optional `settings-yaml` extra | Selecting YAML without it fails startup. |
| Dotenv grammar | Assignment, full-line comments, and basic quotes | No `export`, interpolation, multiline, shell expansion, or inline comments. |
| Dotenv prefix | `env_prefix` is not applied | Dotenv keys map directly to model paths; process-environment keys use the configured prefix. |
| Nested environment | `__` traverses declared named model fields | No list-index or arbitrary mapping-key syntax. |
| Unknown environment | Ignored | Validate deployment names separately to catch misspellings. |
| Source values | Environment, dotenv, and CLI values stay text until final decode | Conversion errors fail startup. |
| CLI secrets | Any override targeting `Secret[T]` is rejected | Supply secrets by protected environment or file. |
| Direct ASGI overrides | No implicit `BootstrapContext` | `--set` works only with `tori-py run`; direct hosting uses normal sources/factory configuration. |
| Custom codec | Controls final conversion through `Codec` | Parsing, precedence, and merging stay framework-owned. |
| Secret storage | None | Integrate deployment secret management explicitly. |

## Testing

| Area | Current boundary | Consequence or alternative |
| --- | --- | --- |
| Provider override boundary | Exported token in an explicit module, or exported global token | Private-provider override shortcuts are rejected. |
| Override timing | Before compilation only | Builders seal on `compile()` and cannot mutate running applications. |
| Override scope | Fluent replacement declarations use default singleton scope | Replace a deferred module when a scoped test declaration is required. |
| Module replacement | Deferred descriptors only | Static composition is tested through its root or a replacement dynamic boundary. |
| HTTP client | Async HTTPX extra | No built-in synchronous client. |
| Lifespan | TestingModule starts directly; ASGITransport does not drive lifespan | Test the exported wrapper with an explicit lifespan task when lifespan itself is the subject. |
| Network fidelity | In-process ASGI only | It does not test sockets, TLS, proxy trust, server limits, workers, or signal delivery. Add deployed tests. |
| Internals | No mutable cache/resource-stack access | Assert public resolution, behavior, hooks, and cleanup outcomes. |

## Integrations Not In Core

| Area | Core framework boundary |
| --- | --- |
| Persistence and ORM | No database, repository generator, transaction policy, or migration runner. |
| Brokers and distributed messaging | No built-in broker, RPC transport, outbox/inbox, or exactly-once guarantee. |
| CQRS and event sourcing | Not a core dependency; use independently versioned packages when their contracts fit. |
| Jobs and scheduling | No job queue, scheduler, retry engine, or distributed lock. |
| OpenAPI and UI | Not built into core; the optional package is separate and does not enforce runtime security. |
| FastAPI | No FastAPI driver or runtime dependency. |
| Pydantic | No required integration; default conversion uses msgspec. |
| External DI containers | No bridge in v1. |

Use Starlette directly when its smaller, transport-specific model fits better.
Use ToriPy when explicit modules, provider visibility, scopes, and lifecycle
ownership justify the framework boundary. Do not infer NestJS feature parity
from shared terminology.
