# Tutorials

These tutorials build applications step by step and connect each result to the
detailed guides. Start with the path that matches the application you want to
build; use the guide hubs when you need the complete contract or API surface.

Tutorial code is maintained as tested source under `examples/tori_py/`, but the
three-part Task API series starts from an empty consumer project and includes
every required file on the page. Repository module paths are verification
artifacts, not installed application templates.

## Task API Series

Build one application in sequence. Each part keeps the same public HTTP contract
while changing the architecture behind it:

| Part | Tutorial | Architecture checkpoint |
| --- | --- | --- |
| 1 | [Build a Task API](task-api.md) | One application with an HTTP controller, application service, and in-memory repository |
| 2 | [Add CQRS](cqrs-application.md) | The same service and repository behind command/query buses, with asynchronous local observers |
| 3 | [Distribute the Task API](distributed-application.md) | An HTTP gateway, typed task-service RPC, and idempotent audit event consumer |

## Choose A Learning Path

| Path | Read in this order | You will learn |
| --- | --- | --- |
| Beginner | [Installation](../getting-started/installation.md) -> [First Application](../getting-started/first-application.md) -> [Project Structure](../getting-started/project-structure.md) -> [Task API tutorial](task-api.md) | Application factories, explicit modules, constructor injection, HTTP, lifecycle, and testing |
| Web API | [Task API tutorial](task-api.md) -> [HTTP](../http/index.md) -> [Request Pipeline](../pipeline/index.md) -> [OpenAPI](../openapi/index.md) | Typed request conversion, guards, errors, request scope, ASGI hosting, and generated API documentation |
| CQRS | [Task API Part 1](task-api.md) -> [Part 2: Add CQRS](cqrs-application.md) -> [CQRS guide](../techniques/cqrs/index.md) -> [Event Sourcing](../techniques/event-sourcing/index.md) | Commands, queries, local event fan-out, handler scopes, and the next persistence model |
| Distributed application | [Task API Part 1](task-api.md) -> [Part 2: Add CQRS](cqrs-application.md) -> [Part 3: Distribute the API](distributed-application.md) -> [Microservices](../techniques/microservices/index.md) | Service ownership, typed RabbitMQ RPC, at-least-once events, outbox boundaries, deduplication, and failure policy |
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

The tutorials demonstrate behavior and boundaries. They do not turn educational
credentials, in-memory adapters, example schema creation, or a local Compose
stack into production defaults.
