# Tori Py

Tori Py is a family of independently installable, typed Python packages for
building explicit modular applications. The family covers dependency injection,
ASGI, CQRS, event sourcing, SQLAlchemy, OpenAPI, microservices, and persistent
streams without forcing every integration into the core framework.

Tori Py requires Python 3.14.

## Packages

| Distribution | Import | Purpose |
| --- | --- | --- |
| `tori-py-framework` | `tori_py` | Modular application framework, DI, lifecycle, and Starlette ASGI driver |
| `tori-py-cqrs-core` | `tori_py_cqrs_core` | Framework-neutral CQRS primitives and transports |
| `tori-py-cqrs-fastapi` | `tori_py_cqrs_fastapi` | FastAPI adapter for the CQRS core |
| `tori-py-cqrs` | `tori_py_cqrs` | Tori Py CQRS module and handler discovery |
| `tori-py-cqrs-event-sourcing-core` | `tori_py_cqrs_event_sourcing_core` | Framework-neutral event-sourcing primitives |
| `tori-py-cqrs-event-sourcing` | `tori_py_cqrs_event_sourcing` | Transactional event-sourcing integration for Tori Py CQRS |
| `tori-py-sqlalchemy` | `tori_py_sqlalchemy` | Async SQLAlchemy lifecycle, repositories, and transactions |
| `tori-py-openapi` | `tori_py_openapi` | OpenAPI 3.1 and Swagger UI integration |
| `tori-py-microservices` | `tori_py_microservices` | Transport-neutral RPC and event delivery |
| `tori-py-persistent-streams-core` | `tori_py_persistent_streams_core` | Framework-neutral persistent-log contracts |
| `tori-py-persistent-streams` | `tori_py_persistent_streams` | Tori Py persistent-stream handlers and publishers |
| `tori-py-persistent-streams-rabbitmq` | `tori_py_persistent_streams_rabbitmq` | Provisional RabbitMQ Streams adapter |

## Installation

Install only the packages an application uses:

```bash
uv add tori-py-framework
uv add tori-py-cqrs tori-py-cqrs-event-sourcing
uv add tori-py-sqlalchemy tori-py-openapi
uv add "tori-py-microservices[rabbitmq]"
```

## Status

The package family is beta. The coordinated initial release train is `0.1.0`,
while each distribution follows independent Semantic Versioning after that
train. APIs may change between minor releases before `1.0.0`.

The RabbitMQ persistent-streams adapter is released provisionally and remains
conditional on its documented broker topology, driver pin, operational
preflight, checkpoint model, and deployment limits. Its `0.1.0` version does not
claim unconditional production readiness.

## Project Links

- [Documentation](https://mikeoz32.github.io/tori-py/)
- [Issue tracker](https://github.com/mikeoz32/tori-py/issues)
- [Changelog](https://github.com/mikeoz32/tori-py/blob/main/CHANGELOG.md)
- [Security policy](https://github.com/mikeoz32/tori-py/blob/main/SECURITY.md)
- [Contributing](https://github.com/mikeoz32/tori-py/blob/main/CONTRIBUTING.md)

The future public repository is <https://github.com/mikeoz32/tori-py>.

## License

Tori Py is licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE)
for attribution and repository-history information.
