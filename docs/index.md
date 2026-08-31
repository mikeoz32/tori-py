# ToriPy

ToriPy is a typed Python 3.14 framework family for applications that benefit
from explicit module composition, constructor dependency injection, deterministic
lifecycle, and clear infrastructure boundaries. The core framework provides an
ASGI HTTP stack; independently installable packages add CQRS, event sourcing,
SQLAlchemy, OpenAPI, microservices, and persistent streams.

There is no package scan and no process-global provider registry. Application
structure is compiled from public Python declarations before startup, so
visibility, dependency cycles, and invalid scope paths fail before traffic is
accepted.

## Start Here

=== "New application"

    1. [Install the framework](getting-started/installation.md).
    2. Build the [first application](getting-started/first-application.md).
    3. Follow the tested [Task API tutorial](tutorials/task-api.md).

=== "NestJS or FastAPI user"

    1. Read the [concepts map](concepts-map.md).
    2. Learn [modules](fundamentals/modules.md),
       [providers and DI](fundamentals/providers-and-di.md), and the
       [request pipeline](pipeline/index.md).
    3. Check the explicit [limitations](operations/limitations.md).

=== "Adding infrastructure"

    Choose the owning package from the [package decision matrix](packages.md),
    then use the relevant guide under Techniques. Each integration remains
    independently installable and documents its own durability and lifecycle
    boundary.

=== "Operating a service"

    Start with [CLI and ASGI hosting](operations/cli-and-asgi.md), then review
    [deployment](operations/deployment.md), [security](operations/security.md),
    and package-specific operational guides.

## Framework Capabilities

- Explicit static and dynamic modules with local, imported, exported, and global
  provider visibility.
- Value, class, factory, and alias providers with singleton, request, and
  transient scopes.
- Managed sync and async resources, startup rollback, lifecycle hooks, work
  scopes, quiescence, and bounded shutdown.
- Starlette-backed controllers, explicit raw request binding, bounded body
  streaming, portable responses, and Problem Details errors.
- Middleware, guards, pipes, msgspec validation, interceptors, and exception
  filters with documented ordering and cancellation behavior.
- Typed settings, secret-aware bootstrap overrides, structured logging,
  discovery/reflection, and test-time provider/module replacement.

`NestApplication` owns driver-neutral compilation and lifecycle. `tori_py.http`
owns route plans and execution semantics. `tori_py.starlette` is the explicit
ASGI driver boundary.

## Optional Techniques

| Need | Guide | Package |
| --- | --- | --- |
| OpenAPI 3.1 and Swagger UI | [OpenAPI](openapi/index.md) | `tori-py-openapi` |
| Async ORM lifecycle and repositories | [SQLAlchemy](techniques/sqlalchemy/index.md) | `tori-py-sqlalchemy` |
| Commands, queries, and in-process events | [CQRS](techniques/cqrs/index.md) | `tori-py-cqrs-core`, `tori-py-cqrs`, or `tori-py-cqrs-fastapi` |
| Event-sourced aggregates and command transactions | [Event Sourcing](techniques/event-sourcing/index.md) | `tori-py-cqrs-event-sourcing-core` and optional ToriPy integration |
| Service RPC and broker events | [Microservices](techniques/microservices/index.md) | `tori-py-microservices` |
| Replayable partitioned logs | [Persistent Streams](techniques/persistent-streams/index.md) | the persistent-stream package family |

## Boundaries

The framework core does not provide authentication, authorization policy,
migrations, background jobs, WebSockets, templates, static files, or a Pydantic
integration. Optional packages do not erase those boundaries or silently compose
transactions across HTTP, databases, brokers, and checkpoints.

All packages are currently beta. In-memory transports, stores, logs, and
checkpoints are semantic references rather than durable production adapters.
Read [Why ToriPy](why-tori-py.md), [Packages](packages.md), and the
[production limitations](operations/limitations.md) before choosing a stack.
