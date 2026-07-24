# Nestpy Example

Install the CLI extra and serve the example with:

```text
uv add 'nestpy[cli]'
nestpy run examples.nestpy.app:create_application --set greeting=hello
```

The application uses public Nestpy imports, typed settings, a request-scoped
provider, a guard, the opt-in msgspec validation pipe, a filter, and the
production Starlette lifespan wrapper.

For a persistence example using async SQLAlchemy sessions, explicit native
transactions, typed settings, and no CQRS dependency, see
[`reference_apps/sqlalchemy_task_api`](reference_apps/sqlalchemy_task_api/README.md).

For a larger event-driven example using automatic `nestpy-cqrs` handler
discovery, scoped command handling, event fan-out, and a read projection, see
[`cqrs/advanced`](cqrs/advanced/README.md).

For a full event-sourced community project with three aggregates, schema
upcasting, optimistic concurrency, request-scoped Unit of Work, checkpointed
projections, privacy rules, moderation, and HTTP endpoints, see
[`cqrs/event_sourcing`](cqrs/event_sourcing/README.md).
