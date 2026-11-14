# Tutorials

These tutorials build applications step by step and connect each result to the
detailed guides. Start with the path that matches the application you want to
build; use the guide hubs when you need the complete contract or API surface.

Tutorial code is maintained as tested source under `examples/tori_py/`, but the
four-part Task API series starts from an empty consumer project and includes
every required file on the page. Repository module paths are verification
artifacts, not installed application templates.

## Task API Series

Build one application in sequence. Parts 1-3 keep the same HTTP contract while
changing the architecture behind it. Part 4 preserves the existing paths and
`Task` representation, adds rename, and deliberately changes reads to eventual
projection semantics:

| Part | Tutorial | Architecture checkpoint |
| --- | --- | --- |
| 1 | [Build a Task API](task-api.md) | One application with an HTTP controller, application service, and in-memory repository |
| 2 | [Add CQRS](cqrs-application.md) | The same service and repository behind command/query buses, with asynchronous local observers |
| 3 | [Distribute the Task API](distributed-application.md) | An HTTP gateway, typed task-service RPC, and idempotent audit event consumer |
| 4 | [Add Event Sourcing](event-sourced-application.md) | Event-sourced command writes, projection-owned reads, and persistent-stream delivery to independent consumers |

[Document the Task API with OpenAPI](openapi-task-api.md) branches from Part 1.
It keeps the existing routes, serves an OpenAPI 3.1 document and Swagger UI,
documents Problem Details error responses, and adds a delete route protected by
a bearer token.

[Build a Live Task Board](live-task-board.md) branches from Part 2 instead of
following Part 4. It keeps the same REST API and one process, and adds a
LiveView page that creates tasks through the command bus, validates as the user
types, and updates every open board through a CQRS event handler.

[Add a Live Task Feed with WebSockets](websocket-task-feed.md) branches from
Part 1. It keeps the same REST API and adds a WebSocket gateway that sends a
snapshot of the tasks and then every new task, with an `Origin` check and
per-connection state that cleans itself up.

[Publish Task Activity to a Persistent Stream](stream-task-activity.md)
branches from Part 1. It publishes a versioned record after each create,
builds an activity read model with a stream handler, tests with the in-memory
adapter, and runs the same code on RabbitMQ Streams with Docker Compose.

[Persist the Task API with SQLAlchemy](sqlalchemy-task-api.md) branches from
Part 1. It keeps the same REST API, stores tasks in SQLite through async
SQLAlchemy, adds an all-or-nothing batch route, and creates the schema with
Alembic migrations.

[Authenticate and Audit the Task API](pipeline-and-auth.md) branches from Part 1.
It adds a maintenance-mode middleware, a guard that identifies the caller from a
bearer token, role guards, and an audit interceptor, registered at the global,
controller, and route levels. Reads stay public; creating a task needs a token.

## Choose A Learning Path

| Path | Read in this order | You will learn |
| --- | --- | --- |
| Beginner | [Installation](../getting-started/installation.md) -> [First Application](../getting-started/first-application.md) -> [Project Structure](../getting-started/project-structure.md) -> [Task API tutorial](task-api.md) | Application factories, explicit modules, constructor injection, HTTP, lifecycle, and testing |
| Web API | [Task API tutorial](task-api.md) -> [HTTP](../http/index.md) -> [Request Pipeline](../pipeline/index.md) -> [OpenAPI](../openapi/index.md) | Typed request conversion, guards, errors, request scope, ASGI hosting, and generated API documentation |
| Database | [Task API Part 1](task-api.md) -> [Persist with SQLAlchemy](sqlalchemy-task-api.md) -> [SQLAlchemy](../techniques/sqlalchemy/index.md) | Settings-driven engines, repositories, automatic and explicit transactions, Alembic migrations, and database tests |
| CQRS | [Task API Part 1](task-api.md) -> [Part 2: Add CQRS](cqrs-application.md) -> [CQRS guide](../techniques/cqrs/index.md) -> [Event Sourcing](../techniques/event-sourcing/index.md) | Commands, queries, local event fan-out, handler scopes, and the next persistence model |
| Distributed application | [Task API Part 1](task-api.md) -> [Part 2: Add CQRS](cqrs-application.md) -> [Part 3: Distribute the API](distributed-application.md) -> [Microservices](../techniques/microservices/index.md) | Service ownership, typed RabbitMQ RPC, at-least-once events, outbox boundaries, deduplication, and failure policy |
| Event-sourced application | [Task API Part 1](task-api.md) -> [Part 2: Add CQRS](cqrs-application.md) -> [Part 3: Distribute the API](distributed-application.md) -> [Part 4: Add Event Sourcing](event-sourced-application.md) -> [Event Sourcing](../techniques/event-sourcing/index.md) -> [Persistent Streams](../techniques/persistent-streams/index.md) | Aggregate persistence, direct event publication, projection-owned reads, consumer groups, checkpoints, and eventual consistency |
| Interactive UI | [Task API Part 1](task-api.md) -> [Part 2: Add CQRS](cqrs-application.md) -> [Build a Live Task Board](live-task-board.md) -> [LiveView](../techniques/liveview/index.md) -> [LiveView UI](../techniques/liveview-ui/index.md) -> [LiveView example](https://github.com/mikeoz32/tori-py/tree/main/examples/tori_py/liveview) | Server-rendered pages, Phoenix events, streams, server-initiated updates, forms, and themes without client JavaScript |
| FastAPI | [CQRS with FastAPI](../techniques/cqrs/fastapi.md) -> [tested profile application](https://github.com/mikeoz32/tori-py/blob/main/examples/profile_app.py) | Using CQRS core under FastAPI-owned registration and lifespan without the Tori Py framework |
| Operator | [Operations](../operations/index.md) -> [Deployment](../operations/deployment.md) -> [Limitations](../operations/limitations.md) | Lifespan, readiness, process supervision, graceful shutdown, security boundaries, and production checks |

## Before Choosing Packages

Tori Py is a family of independently installable packages, not one all-in-one
runtime. Use the [package decision matrix](../packages.md) to select the smallest
integration boundary that owns your requirement.

In particular, the CQRS event bus, RabbitMQ microservice events, event-store
records, and persistent streams solve different problems. Do not select one only
because each uses the word "event."

## Operator Branches

After the general operator path, continue only into the subsystem you deploy:

| Subsystem | Operational guide |
| --- | --- |
| SQLAlchemy | [Testing and migrations](../techniques/sqlalchemy/testing-and-migrations.md) |
| RabbitMQ RPC and events | [Microservice operations](../techniques/microservices/operations.md) |
| Persistent streams | [Persistent stream operations](../techniques/persistent-streams/operations.md) |
| LiveView | [LiveView configuration and security](../techniques/liveview/configuration-and-security.md) |

The tutorials demonstrate behavior and boundaries. They do not turn educational
credentials, in-memory adapters, example schema creation, or a local Compose
stack into production defaults.
