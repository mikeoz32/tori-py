# Packages

Tori Py is a family of 13 independently installable distributions. There is no
all-in-one metapackage: install the smallest set that owns the contracts your
application uses. Every distribution currently requires Python `>=3.14,<3.15`,
is typed, and is on the coordinated `0.1.0` beta release train.

## Decision matrix

| Need | Install and import | Choose it when | Important boundary or caveat |
| --- | --- | --- | --- |
| Modules, dependency injection, lifecycle, HTTP, or Starlette ASGI | `tori-py-framework` / `tori_py` | Building a Tori Py application or integration | Requires `msgspec` and Starlette. It does not include persistence, authentication, CQRS, brokers, jobs, or OpenAPI. |
| Framework-neutral commands, queries, events, buses, and transports | `tori-py-cqrs-core` / `tori_py_cqrs_core` | CQRS is needed without coupling to a web or DI framework | Runtime dependency-free. Its in-memory transport is a process-local reference, not durable messaging. |
| CQRS in FastAPI | `tori-py-cqrs-fastapi` / `tori_py_cqrs_fastapi` | A FastAPI application needs the CQRS core buses and scoped handler provider | Depends on FastAPI and CQRS core, not Tori Py framework. It does not make FastAPI part of CQRS core. |
| CQRS in a Tori Py application | `tori-py-cqrs` / `tori_py_cqrs` | Handlers should be Tori Py providers discovered from the compiled graph | Depends on Tori Py framework and CQRS core. Dispatch gets a fresh module-qualified work scope; it does not provide durable delivery or persistence. |
| Framework-neutral aggregates, event schemas, stores, repositories, and Unit of Work | `tori-py-cqrs-event-sourcing-core` / `tori_py_cqrs_event_sourcing_core` | Implementing or testing event-sourced domain and storage contracts independently | Depends only on CQRS core. `InMemoryEventStore` is not durable; production requires an application store adapter and usually an outbox. |
| Automatic event-sourced command transactions in Tori Py CQRS | `tori-py-cqrs-event-sourcing` / `tori_py_cqrs_event_sourcing` | Decorated command handlers need request-scoped repositories and outcome-aware commit finalization | Composes framework, CQRS, and event-sourcing core. It does not publish stored events, add an outbox, retry commands, or create distributed transactions. |
| Async SQLAlchemy lifecycle, transactions, and repositories | `tori-py-sqlalchemy` / `tori_py_sqlalchemy` | Tori Py should own an async engine or integrate an external one | Depends on Tori Py and `sqlalchemy[asyncio]`. The application installs its async driver and owns models and Alembic migrations. There is no model scan or `AsyncSession` provider. |
| OpenAPI 3.1 and Swagger UI for Tori Py HTTP controllers | `tori-py-openapi` / `tori_py_openapi` | Documentation should be compiled from Tori Py route plans | Depends on Tori Py, `msgspec`, and Starlette's public route compiler. Security and error responses are explicit metadata, not inferred from guards or filters. Default Swagger assets are external CDN assets. |
| Server-rendered interactive pages | `tori-py-liveview` / `tori_py_liveview` | Page, component, and collection state should remain server-directed with a thin browser runtime | Depends on Tori Py and Starlette. Protocol v2 covers pages, structural diffs, connection-local stateful components, and browser-owned streams; nested components, uploads, and `send_info` are not implemented. |
| Transport-neutral RPC and queue-event delivery | `tori-py-microservices` / `tori_py_microservices` | One Tori Py application exposes one logical service or calls service clusters | Base runtime depends on Tori Py and `msgspec`; RabbitMQ is an extra. RPC and events are at least once and need application idempotency/outbox/inbox policy. |
| Framework-neutral partitioned persistent-log contracts | `tori-py-persistent-streams-core` / `tori_py_persistent_streams_core` | Defining an adapter, testing log semantics, or using opaque byte records without Tori Py | Runtime dependency-free. The included in-memory log loses all state at process exit and is not a production adapter. |
| Typed persistent-stream handlers and publishers in Tori Py | `tori-py-persistent-streams` / `tori_py_persistent_streams` | Tori Py should discover stream controllers and own work scopes and checkpoints | Depends on Tori Py and streams core. It contains no broker driver. Delivery is at least once; failed records stop their partition. |
| RabbitMQ native Streams adapter | `tori-py-persistent-streams-rabbitmq` / `tori_py_persistent_streams_rabbitmq` | A deployment has explicitly accepted the adapter's narrow RabbitMQ contract | Provisional. Requires RabbitMQ 4.1, the Streams plugin, CPython 3.14, and exactly `rstream==1.0.1`. Important production and cluster gates remain incomplete. |

Do not choose a persistent stream for aggregate event storage merely because
both contain events. Event sourcing owns aggregate streams and atomic expected
versions; persistent streams own partitioned replay and checkpoints. Likewise,
the CQRS event bus is in-process, while microservices events and persistent
streams have different transport, settlement, and replay contracts.

## Installation

Use `uv` in a consumer project:

```text
uv add tori-py-framework
uv add tori-py-cqrs-core
uv add tori-py-cqrs-fastapi
uv add tori-py-cqrs
uv add tori-py-cqrs-event-sourcing-core
uv add tori-py-cqrs-event-sourcing
uv add tori-py-sqlalchemy
uv add tori-py-openapi
uv add tori-py-liveview
uv add tori-py-microservices
uv add tori-py-persistent-streams-core
uv add tori-py-persistent-streams
uv add tori-py-persistent-streams-rabbitmq
```

Framework extras are opt-in:

```text
uv add "tori-py-framework[cli]"
uv add "tori-py-framework[testing]" --dev
uv add "tori-py-framework[settings-yaml]"
uv add "tori-py-framework[cli,testing,settings-yaml]"
```

RabbitMQ support for the microservices package is also opt-in:

```text
uv add "tori-py-microservices[rabbitmq]"
```

Typical combinations are:

```text
# Tori Py HTTP API with SQLAlchemy and documentation
uv add "tori-py-framework[cli]" tori-py-sqlalchemy tori-py-openapi

# Tori Py CQRS and event-sourced commands
uv add tori-py-cqrs tori-py-cqrs-event-sourcing

# Broker-free portable CQRS library
uv add tori-py-cqrs-core

# RabbitMQ RPC and event service
uv add "tori-py-microservices[rabbitmq]"

# Tori Py persistent streams with the provisional RabbitMQ adapter
uv add tori-py-persistent-streams-rabbitmq
```

Transitive dependencies are installed by `uv`; listing them again is not
required. Install application-owned dependencies separately. Examples include
an async database driver such as `aiosqlite` or `psycopg`, Alembic for
migrations, and an ASGI server when the framework `cli` extra is not used.

## Dependency boundaries

The arrows below are runtime dependencies, not recommended imports:

```text
tori-py-framework -> msgspec, starlette

tori-py-cqrs-core -> Python standard library
tori-py-cqrs-fastapi -> tori-py-cqrs-core, fastapi
tori-py-cqrs -> tori-py-cqrs-core, tori-py-framework
tori-py-cqrs-event-sourcing-core -> tori-py-cqrs-core
tori-py-cqrs-event-sourcing
  -> tori-py-cqrs-core
  -> tori-py-cqrs-event-sourcing-core
  -> tori-py-framework
  -> tori-py-cqrs

tori-py-sqlalchemy -> tori-py-framework, sqlalchemy[asyncio]
tori-py-openapi -> tori-py-framework, msgspec, starlette
tori-py-liveview -> tori-py-framework, starlette
tori-py-microservices -> tori-py-framework, msgspec
tori-py-microservices[rabbitmq] -> aio-pika

tori-py-persistent-streams-core -> Python standard library
tori-py-persistent-streams
  -> tori-py-framework, tori-py-persistent-streams-core
tori-py-persistent-streams-rabbitmq
  -> tori-py-persistent-streams
  -> tori-py-persistent-streams-core
  -> rstream==1.0.1
```

The boundaries are intentionally one-way:

- Tori Py framework does not import CQRS, SQLAlchemy, OpenAPI, LiveView,
  microservices, or persistent-stream integrations.
- CQRS core does not import Tori Py, FastAPI, Pydantic, SQLAlchemy, or a DI
  framework.
- Persistent-streams core is standard-library-only and does not import Tori Py
  or a broker driver.
- Broker clients stay in optional integration or adapter packages.
- Optional integrations discover only explicitly compiled providers or
  controllers. They do not scan installed packages or use process-global
  registries.
- Package versions are independent after the initial release train. Integration
  manifests currently constrain coordinated dependencies to `>=0.1.0,<0.2.0`;
  let `uv` solve a compatible set rather than assuming every future version can
  be mixed.

## Maturity and production decisions

All 13 distributions are beta. Before `1.0.0`, compatible-looking APIs may still
change in a minor release. Pin and test the complete resolved set in an
application lockfile.

The beta label is not the only production decision:

- In-memory transports, stores, logs, repositories, projections, and checkpoint
  stores are semantic references or test fixtures. They do not become durable
  because an integration manages their lifecycle.
- SQLAlchemy integration manages resources and transaction boundaries, not
  migrations, schema creation, driver selection, isolation policy, or database
  operations.
- OpenAPI describes declared route metadata. It does not validate responses or
  prove that documented security is enforced. Swagger UI's default external
  assets need network and Content Security Policy review.
- LiveView runs page events at most once per accepted WebSocket frame but does
  not make application side effects transactional or durable. Deployments must
  use TLS, a strong shared token secret, explicit proxy-aware origins, and their
  own authorization and idempotency policy.
- Microservices RabbitMQ RPC and durable events are at least once. Publisher
  confirms do not prove handler execution; timeout and connection loss can leave
  outcomes unknown. Production applications need stable idempotency keys and,
  where required, transactional outbox/inbox boundaries.
- Persistent streams checkpoint only after successful handler and scope cleanup,
  but handler side effects are not atomic with checkpoints. Duplicate processing
  is valid. Retention gaps and poison records require explicit operator policy.
- `tori-py-persistent-streams-rabbitmq` is explicitly provisional. Timestamp and
  relative starts are unsupported; public bounds are unavailable; automatic
  reconnect is disabled; named-publication content association does not survive
  restart; broker-managed checkpoints are single-instance only; TLS/fault,
  external-store multi-replica fencing, full Super Stream movement, and other
  release gates remain incomplete. Review its package `README.md`,
  `OPERATIONS.md`, and architecture before any deployment.

Production readiness is therefore an application and adapter assessment, not a
property inherited from installing a beta distribution.
