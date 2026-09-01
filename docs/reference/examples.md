# Examples

The repository contains small learning examples, package examples, and composed
reference applications. Commands in the first section are for a checkout of this
repository and use the workspace's locked dependencies. The `examples` package
is not installed as part of any Tori Py distribution.

## Repository commands

Run these commands from the repository root, `C:\work\tori-py`.

Prepare the complete workspace once when running framework and CLI examples:

```text
uv sync --all-packages --all-groups --extra cli
```

Individual package test commands can also let `uv run` synchronize the required
workspace environment. Do not use `uv add` to modify the repository merely to
run an existing example.

### Framework overview

| Example | Exact command | Demonstrates |
| --- | --- | --- |
| `examples/tori_py/app.py` | `uv run tori-py run examples.tori_py.app:create_application --set greeting=hello` | Typed settings, request scope, a guard, msgspec validation, a filter provider, and the CLI factory path |

Request `GET /example/health?count=2` while it is running.

### Getting started

| Example | Exact command | Demonstrates |
| --- | --- | --- |
| Hello World | `uv run tori-py run examples.tori_py.getting_started.hello_world.app:create_application` | Smallest controller, root module, async factory, and ASGI wrapper |
| First Provider | `uv run tori-py run examples.tori_py.getting_started.first_provider.app:create_application` | Explicit `ClassProvider` and constructor injection |
| First Settings | `uv run tori-py run examples.tori_py.getting_started.first_settings.app:create_application` | `SettingsModule.for_root()` and a typed settings provider |
| Project Structure | `uv run tori-py run examples.tori_py.getting_started.project_structure.app:create_application` | Separate controllers, services, and explicit module composition without scanning |
| Async Factory | `uv run tori-py run examples.tori_py.getting_started.async_factory.app:create_application` | Compilation versus lifespan-owned startup |
| ASGI Wrapper | `uv run tori-py run examples.tori_py.getting_started.asgi_wrapper.app:create_application` | Exporting `asgi(create_application)` for an ASGI server |
| CLI Run | `uv run tori-py run examples.tori_py.getting_started.cli_run.app:create_application` | The supported `tori-py run module:factory` path |
| First Test | `uv run pytest examples/tori_py/getting_started/first_test/test_example.py` | `TestingModule`, an exported provider override, HTTPX ASGI requests, and lifecycle cleanup |

Each serving command uses the CLI extra installed by the repository preparation
command. Stop the server normally so ASGI lifespan can run application shutdown.

### HTTP reference applications

| Example | Exact command | Demonstrates |
| --- | --- | --- |
| In-memory Task API | `uv run tori-py run examples.tori_py.reference_apps.task_api.app:create_application` | Modules, typed settings, singleton repository lifecycle, request provider, write guard, validation, domain filter, and CLI/ASGI composition |
| SQLAlchemy Task API | `uv run tori-py run examples.tori_py.reference_apps.sqlalchemy_task_api.app:create_application` | Async SQLite, `SqlAlchemyModule.for_root_async()`, custom repository, automatic operation transactions, DTO responses, and application-owned schema setup |

The Task API also exports a direct ASGI callable:

```text
uv run uvicorn examples.tori_py.reference_apps.task_api.app:application
```

The SQLAlchemy application can be hosted directly and tested with:

```text
uv run uvicorn examples.tori_py.reference_apps.sqlalchemy_task_api.app:application --reload
uv run pytest examples/tori_py/reference_apps/sqlalchemy_task_api -q
```

The SQLAlchemy example defaults to `sqlalchemy_tasks.db`. Its startup schema
creation is deliberately example-owned; it is not a migration feature of
`tori-py-sqlalchemy`.

### Task API tutorial series

The first three snapshots preserve one HTTP contract while evolving the
implementation. Part 4 keeps the existing paths and `Task` representation, adds
rename, and deliberately moves GET semantics to an eventual projection. The
isolated-project smoke test applies all four in order to the same temporary
consumer project.

| Part | Exact command | Demonstrates |
| --- | --- | --- |
| Ordinary Task API | `uv run pytest examples/tori_py/tutorials/task_api/task_app/test_app.py -q` | Controller, application service, singleton in-memory repository, filters, and lifespan |
| CQRS Task API | `uv run pytest examples/tori_py/tutorials/cqrs_task_api/task_app/test_app.py -q` | The unchanged service behind command/query handlers plus asynchronous audit and metrics observers |
| Distributed Task API | `uv run pytest examples/tori_py/tutorials/distributed_task_api/task_app/test_system.py -q` | Three application roots, typed RPC, local CQRS, integration events, and idempotent audit over an in-memory transport |
| Event-Sourced Task API | `uv run pytest examples/tori_py/tutorials/event_sourced_task_api/task_app -q` | Event-sourced commands, projection-owned reads, persistent-stream relay, and independent projection and audit consumers |

Run the complete source-checkout evolution check with:

```text
uv run pytest packages/tori-py/tests/docs/test_task_api_tutorial_series.py -q
```

### CQRS and event sourcing

| Example | Exact command | Demonstrates |
| --- | --- | --- |
| Advanced CQRS Task API | `uv run tori-py run examples.tori_py.cqrs.advanced.app:create_application` | Automatic handler discovery, handler scopes, event fan-out, and an in-process read projection |
| Event-sourced community tests | `uv run pytest examples/tori_py/cqrs/event_sourcing -q` | Three aggregates, explicit schemas/upcasting, automatic command transactions, synchronization, optimistic concurrency, projection checkpoints, privacy, and moderation |
| Event-sourced community HTTP app | `uv run uvicorn examples.tori_py.cqrs.event_sourcing.app:application` | The same project through its production ASGI lifespan wrapper |

The advanced CQRS projection is non-durable, and its write plus event publication
is not atomic. The event-sourcing project uses `InMemoryEventStore` and an
in-memory projection; its tests prove semantics, not production durability.

### FastAPI CQRS

`examples/profile_app.py` is the FastAPI acceptance application for
`tori-py-cqrs-fastapi`:

```text
uv run uvicorn examples.profile_app:create_profile_app --factory
uv run pytest tests/test_fastapi_adapter.py -q
```

It demonstrates adapter-owned command, query, and event handler registration,
FastAPI bus dependencies, and adapter lifespan. It does not use Tori Py
framework.

### OpenAPI

`examples/tori_py/openapi/app.py` is both runnable and acceptance-tested:

```text
uv run uvicorn examples.tori_py.openapi.app:application
uv run pytest examples/tori_py/openapi -q
```

It demonstrates OpenAPI 3.1 route discovery, schemas, explicit bearer security,
public route override, response metadata, Swagger UI, guard enforcement, and a
portable `HttpResponse` export. Browse `/openapi.json` and `/docs`; the protected
member route accepts the educational `Bearer example-token` value only.

### Microservices

The small microservices examples are exercised as one suite:

```text
uv run pytest examples/tori_py/microservices -q
```

| Source | Demonstrates |
| --- | --- |
| `rpc_service.py` | Direct RPC controller discovery, several methods, and hybrid HTTP/RPC composition |
| `replicas.py` | Competing in-memory replicas and one `ServiceCluster` calling multiple logical services |
| `events.py` | `SERVICE_POOL`, `SINGLETON`, ephemeral broadcast, and reliable broadcast metadata |
| `policies.py` | Finite offline RPC deadline and an application-owned outbox relay boundary |

These are in-memory contract examples. They do not claim durable queues, strict
round robin, live membership, exactly-once handling, or a built-in outbox.

### Persistent streams

Run the broker-free persistent-stream application or its acceptance test:

```text
uv run python -m examples.tori_py.persistent_streams.app
uv run pytest examples/tori_py/persistent_streams -q
```

It demonstrates a typed codec, pipe, partition metadata, checkpointed handler,
global stream root, in-memory adapter lifecycle, and raw, named, and Protocol
publisher surfaces. The process intentionally uses the in-memory adapter and is
not a RabbitMQ production test.

### Four-process microservices application

The application under `examples/tori_py/microservices_app` requires Docker,
RabbitMQ, and PostgreSQL. Starting and stopping infrastructure uses Docker
Compose rather than `uv`:

```text
docker compose -f examples/tori_py/microservices_app/compose.yaml up --build
docker compose -f examples/tori_py/microservices_app/compose.yaml down -v
```

After the gateway readiness check passes, run the exact `uv` smoke command:

```text
uv run python -m examples.tori_py.microservices_app.smoke
```

Broker-free application-root tests are:

```text
uv run pytest examples/tori_py/microservices_app -q
```

The stack demonstrates four independent processes: catalog and orders services
with local CQRS, service-owned PostgreSQL databases and dedicated schema
initialization jobs, typed RPC contracts, an HTTP gateway, an orders outbox
relay, and idempotent notification event consumption. The schema jobs call the
application-owned SQLAlchemy metadata's `create_all()`; they are not versioned
migrations or a schema-evolution strategy. Delivery remains at least once; the
outbox may publish duplicates and the consumer deduplicates by event ID.

## Consumer project commands

The repository module paths above work only in a checkout. In a separate
application, initialize a Python 3.14 project and add distributions instead of
synchronizing this workspace:

```text
uv init --python 3.14
uv add "tori-py-framework[cli]"
uv run tori-py run your_package.app:create_application
```

Use the packages required by the chosen architecture:

```text
# Framework HTTP, SQLAlchemy, and OpenAPI
uv add "tori-py-framework[cli]" tori-py-sqlalchemy tori-py-openapi
uv add aiosqlite

# Tori Py CQRS and event sourcing
uv add tori-py-cqrs tori-py-cqrs-event-sourcing

# FastAPI CQRS
uv add tori-py-cqrs-fastapi uvicorn
uv run uvicorn your_package.app:create_application --factory

# RabbitMQ microservices
uv add "tori-py-microservices[rabbitmq]"

# Broker-free persistent streams for application tests
uv add tori-py-persistent-streams

# Provisional RabbitMQ native Streams adapter
uv add tori-py-persistent-streams-rabbitmq
```

For HTTP tests in a consumer project:

```text
uv add --dev "tori-py-framework[testing]" pytest pytest-asyncio
uv run pytest
```

Consumer commands intentionally use `your_package.*`, not `examples.*`. The
examples catalog is a source reference and executable repository test surface;
it is not an installed application template.

## What the examples do not prove

- An in-memory example does not prove durability, broker topology, database
  isolation, TLS, reconnect, or crash behavior.
- A passing portable conformance suite does not replace adapter-specific and
  real-infrastructure tests.
- Educational guards and bearer values are not authentication systems.
- Example schema creation is not a migration strategy.
- Publisher confirmation is not consumer completion, and checkpoint completion
  is not atomicity with arbitrary handler side effects.
- No example changes the package-family beta status or the RabbitMQ
  persistent-stream adapter's provisional status.
