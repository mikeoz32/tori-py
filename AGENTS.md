# Repository Notes

## Project
- Tori Py is a public Python 3.14 framework package family for explicit modules, dependency injection, ASGI applications, CQRS, persistence, OpenAPI, microservices, and persistent streams.
- Keep framework packages independently installable, typed, and explicit about their dependency and adapter boundaries.

## Development
- ALWAYS use `uv` exclusively for Python environments, dependencies, commands, tests, builds, and services.
- Add dependencies with `uv`; run tests and services with `uv`.
- Run quality checks through `uv`: `uv run ruff check .`, `uv run ruff format --check .`, and `uv run ty check tests packages/tori-py-cqrs-core/src packages/tori-py-cqrs-core/tests packages/tori-py-cqrs-event-sourcing-core/src packages/tori-py-cqrs-event-sourcing-core/tests packages/tori-py-cqrs-fastapi/src packages/tori-py-cqrs-fastapi/tests packages/tori-py/src packages/tori-py/tests packages/tori-py-cqrs/src packages/tori-py-cqrs/tests packages/tori-py-cqrs-event-sourcing/src packages/tori-py-cqrs-event-sourcing/tests packages/tori-py-openapi/src packages/tori-py-openapi/tests packages/tori-py-sqlalchemy/src packages/tori-py-sqlalchemy/tests packages/tori-py-microservices/src packages/tori-py-microservices/tests packages/tori-py-persistent-streams-core/src packages/tori-py-persistent-streams-core/tests packages/tori-py-persistent-streams/src packages/tori-py-persistent-streams/tests packages/tori-py-persistent-streams-rabbitmq/src packages/tori-py-persistent-streams-rabbitmq/tests examples/tori_py`.

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
