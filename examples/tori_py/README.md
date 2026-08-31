# ToriPy Example

Install the CLI extra and serve the example with:

```text
uv add 'tori-py-framework[cli]'
tori-py run examples.tori_py.app:create_application --set greeting=hello
```

The application uses public ToriPy imports, typed settings, a request-scoped
provider, a guard, the opt-in msgspec validation pipe, a filter, and the
production Starlette lifespan wrapper.

For a native WebSocket gateway with path and request-scoped provider binding,
see [`websocket`](websocket/README.md).

For a persistence example using async SQLAlchemy sessions, default and custom
repositories, explicit transactions, typed settings, and no CQRS dependency, see
[`reference_apps/sqlalchemy_task_api`](reference_apps/sqlalchemy_task_api/README.md).

For a larger event-driven example using automatic `tori-py-cqrs` handler
discovery, scoped command handling, event fan-out, and a read projection, see
[`cqrs/advanced`](cqrs/advanced/README.md).

For the smaller application built file by file in the documentation, see the
executable [`tutorials/cqrs_task_api`](tutorials/cqrs_task_api/README.md) source.

For a full event-sourced community project with three aggregates, schema
upcasting, optimistic concurrency, request-scoped Unit of Work, checkpointed
projections, privacy rules, moderation, and HTTP endpoints, see
[`cqrs/event_sourcing`](cqrs/event_sourcing/README.md).

For typed persistent stream publishing through raw, named, and Protocol
publishers, plus codec, pipe, partition, checkpoint, and shutdown behavior using
the in-memory adapter, see
[`tori_py_persistent_streams_core`](tori_py_persistent_streams_core/README.md).
