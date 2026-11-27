# Repository Notes

## Project
- Tori Py is a public Python 3.14 framework package family for explicit modules, dependency injection, ASGI applications, CQRS, persistence, OpenAPI, LiveView UI, microservices, and persistent streams.
- Keep framework packages independently installable, typed, and explicit about their dependency and adapter boundaries.

## Development
- ALWAYS use `uv` exclusively for Python environments, dependencies, commands, tests, builds, and services.
- Add dependencies with `uv`; run tests and services with `uv`.
- Run quality checks through `uv`: `uv run ruff check .`, `uv run ruff format --check .`, and `uv run ty check tests packages/tori-py-cqrs-core/src packages/tori-py-cqrs-core/tests packages/tori-py-cqrs-event-sourcing-core/src packages/tori-py-cqrs-event-sourcing-core/tests packages/tori-py-cqrs-fastapi/src packages/tori-py-cqrs-fastapi/tests packages/tori-py/src packages/tori-py/tests packages/tori-py-cqrs/src packages/tori-py-cqrs/tests packages/tori-py-cqrs-event-sourcing/src packages/tori-py-cqrs-event-sourcing/tests packages/tori-py-openapi/src packages/tori-py-openapi/tests packages/tori-py-sqlalchemy/src packages/tori-py-sqlalchemy/tests packages/tori-py-microservices/src packages/tori-py-microservices/tests packages/tori-py-persistent-streams-core/src packages/tori-py-persistent-streams-core/tests packages/tori-py-persistent-streams/src packages/tori-py-persistent-streams/tests packages/tori-py-persistent-streams-rabbitmq/src packages/tori-py-persistent-streams-rabbitmq/tests packages/tori-py-liveview/src packages/tori-py-liveview/tests packages/tori-py-liveview-ui/src packages/tori-py-liveview-ui/tests examples/tori_py`.

## Typing and Runtime Validation
- Trust annotated Python interfaces. `uv run ty check packages tests examples` is a mandatory quality gate for Python changes and must pass alongside Ruff and the relevant tests.
- Do not duplicate annotations with runtime `isinstance`, exact `type`, tuple-shape, element-type, or `Literal` membership checks. Do not add validation-only identity helpers or tests that bypass typing with `Any` merely to demand these checks.
- Validate untrusted data once at its boundary: HTTP/WebSocket payloads, decoded documents, configuration text, and external service responses. Pass typed values into application and rendering code after that boundary.
- Keep semantic and security checks that types cannot express: numeric ranges and finiteness, non-empty accessible names, safe URLs/IDs/selectors, uniqueness, and relationships between arguments. Preserve escaping regardless of the caller's annotations.
- Runtime type dispatch is justified only when supported union variants have different behavior. Prefer separate operations, polymorphism, or a small dispatch function over repeated type branches. Use `@overload` when accepted signatures or return types differ; `typing.overload` describes static signatures and does not implement runtime multimethod dispatch. Do not add overloads with identical results or a dispatch dependency just to hide one clear union branch.
- Use precise annotations and narrow boundary values instead of silencing errors with `Any`, unchecked casts, or ignores. Tests should cover behavior and semantic validation; the mandatory type check owns invalid Python argument types.

## CQRS
- Keep the core package framework-neutral; it must not depend on FastAPI, Pydantic, SQLAlchemy, or a DI framework.
- Preserve clear boundaries between commands, queries, domain/application logic, and infrastructure; do not copy NestJS internals mechanically into Python.
- The architecture, implementation order, and non-goals are recorded in `CQRS_IMPLEMENTATION_PLAN.md`, `TORI_PY_CQRS_EVENT_SOURCING_CORE_IMPLEMENTATION_PLAN.md`, `TORI_PY_CQRS_EVENT_SOURCING_ARCHITECTURE.md`, and the corresponding `spec/tori-py-cqrs*/` specifications.

## Tori Py SQLAlchemy
- The async SQLAlchemy lifecycle/DI integration is governed by `TORI_PY_SQLALCHEMY_ARCHITECTURE.md`, `TORI_PY_SQLALCHEMY_IMPLEMENTATION_PLAN.md`, and `spec/tori-py-sqlalchemy/README.md`.
- Keep engine, session-factory, EntityManager, and explicitly registered repository providers singleton. EntityManager auto-scopes standalone operations, reuses an active transaction through an instance ContextVar with strict owner-task guards, and uses savepoints for explicit same-task nesting; repositories are never bound or cloned. Do not add CQRS, event sourcing, model scanning, generated repository classes, a custom query language, or startup migrations to the integration.

## Tori Py OpenAPI
- The optional OpenAPI 3.1/Swagger UI package is governed by `TORI_PY_OPENAPI_ARCHITECTURE.md`, `TORI_PY_OPENAPI_IMPLEMENTATION_PLAN.md`, and `spec/tori-py-openapi/README.md`.
- Discover controllers through Tori Py `DiscoveryService` and compile mappings through the public transport-neutral controller route compiler. Do not inspect or extend `StarletteAdapter`, infer runtime security or errors, or add FastAPI/Pydantic.

## Tori Py Microservices
- The optional microservices package is governed by `TORI_PY_MICROSERVICES_ARCHITECTURE.md`, `TORI_PY_MICROSERVICES_IMPLEMENTATION_PLAN.md`, and `spec/tori-py-microservices/README.md`.
- Keep RabbitMQ and `aio-pika` outside Tori Py core. One `NestApplication` exposes at most one logical service identity; discover explicitly registered controllers at startup without endpoint modules, package scanning, or global registries.
- RabbitMQ RPC uses one durable queue and one `<namespace>.<service>.v<version>.*` topic binding per logical service. Replicas are equal competing consumers; methods use distinct routing keys but not per-method queues or bindings.
- Treat RPC execution and durable event delivery as at least once. Require finite RPC deadlines, confirmed and routed replies before normal request ACK, no intentional requeue of a proven deleted reply route, and no automatic resend of accepted or indeterminate RPC. Outbox, inbox, idempotency, and application service boundaries remain application concerns.

## Persistent Streams
- Keep `tori-py-persistent-streams-core` framework-neutral and standard-library-only. Broker drivers and the Tori Py integration remain separate packages.
- Preserve explicit at-least-once, checkpoint, retention, reconnect, and broker safety semantics; do not overstate durability, failover, or exactly-once guarantees.

## Tori Py LiveView
- The optional LiveView package is governed by `TORI_PY_LIVEVIEW_ARCHITECTURE.md`, `TORI_PY_LIVEVIEW_IMPLEMENTATION_PLAN.md`, and `spec/tori-py-liveview/README.md`.
- Keep LiveView outside ToriPy core. Pages are explicit request-scoped providers, and the server interoperates with the unchanged pinned official Phoenix 1.8.13 and Phoenix LiveView 1.2.11 JavaScript clients.
- Preserve Phoenix V2 Channels framing, `phx-*` bindings, render-tree/component/stream semantics, finite deadlines, Origin validation, signed mount tokens, component identity/target lifecycle, browser-owned stream operations, serialized connection-local `send_info`, client hooks, pushed events (`e`), event replies (`r`), `send_update`, flash tokens and the `__phoenix_flash__` cookie, connection-task async results cancelled with their owner, connect params, `reload` join errors, changed-only diffs, nested components owned by their page, and child LiveViews joined only under the parent mount that rendered them, with purpose-separated child tokens. Uploads and sticky child LiveViews remain deferred until their official contracts are implemented end to end.

## Tori Py LiveView UI
- The optional UI package is governed by `TORI_PY_LIVEVIEW_UI_ARCHITECTURE.md`, `TORI_PY_LIVEVIEW_UI_IMPLEMENTATION_PLAN.md`, and `spec/tori-py-liveview-ui/README.md`.
- Keep `tori-py-liveview-ui` separately installable and limited to stateless Template helpers, document integration, one stylesheet, and one script of `ToriUi`-prefixed Phoenix hooks. It must reuse LiveView's Phoenix `phx-*`, `JS` command, hook, escaping, render-tree, and component-target contracts rather than adding a client runtime or state model.
- Application state stays in pages and components. Browser-owned presentation state, such as an open menu, a scroll position, or a stored theme choice, uses native elements first, `JS` commands second, and a hook only where neither can express the behavior.
- Keep assets local and content-addressed, selectors prefixed, theme and skin tokens overridable, and keyboard/reduced-motion behavior explicit. Keep color theme and visual skin selection separate; application-owned skins remain CSS-only. Do not add a CDN, Node tooling, external fonts, a global reset, arbitrary caller-controlled attributes/classes, remote or dynamically evaluated script code, application state in hooks, or required dependencies beyond ToriPy and LiveView; optional features ship as extras.
