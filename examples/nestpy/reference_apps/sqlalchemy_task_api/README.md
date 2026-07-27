# Nestpy SQLAlchemy Task API

This reference application uses Nestpy, `nestpy-sqlalchemy`, SQLAlchemy ORM,
and `aiosqlite`. It deliberately has no CQRS, event-sourcing, outbox, generated
repository classes, or automatic request/command transaction layer.

## Run

Run through the Nestpy CLI:

```text
uv run nestpy run examples.nestpy.reference_apps.sqlalchemy_task_api.app:create_application
```

Or run the exported ASGI application directly:

```text
uv run uvicorn examples.nestpy.reference_apps.sqlalchemy_task_api.app:application --reload
```

The default database is a file-backed `sqlalchemy_tasks.db` SQLite database.
Override it through typed settings:

```text
SQLALCHEMY_TASK_API_DATABASE__URL=sqlite+aiosqlite:///tasks.db
```

The HTTP API provides:

```text
POST /tasks
GET  /tasks
GET  /tasks/{task_id}
```

## Boundaries Demonstrated

- `SqlAlchemyModule.for_root_async()` receives `TaskApiSettings` through Nestpy
  annotation-based factory parameter injection.
- The integration owns singleton engine, session factory, and `EntityManager`
  providers.
- `SqlAlchemyModule.for_feature()` registers the decorated `TaskRepository`
  through the global default root.
- `TaskService` uses inherited default CRUD for create/get and the repository's
  custom SQLAlchemy query policy for ordered listing.
- `TaskService` and its controller are stateless singleton providers declared
  with `@injectable()`/`@controller()` and constructor injection.
- Each service method opens a narrow lexical `EntityManager.transaction()`;
  repository operations automatically use that task-local session.
- Controllers return DTOs rather than SQLAlchemy ORM rows.
- Schema creation is an application-owned lifecycle provider. It is included
  only to keep the SQLite example runnable; production applications should use
  Alembic outside startup.

## API Friction Exposed

The example also makes current limitations visible:

- ORM entities detach when their lexical transaction closes. Relationships
  required afterward must be loaded explicitly through SQLAlchemy loader options.
- Nested same-task transaction scopes create savepoints; child-task use is
  rejected rather than sharing an unsafe `AsyncSession`.
- Application-owned startup work that needs the engine requires a lifecycle
  provider because production `NestApplication` has no public resolver.
- Nestpy has no migration, database health-check, response-schema, or OpenAPI
  integration; those concerns remain separate.
- `GET /tasks` intentionally returns every row to keep the example focused; a
  production API needs bounded pagination.

SQLite makes the example self-contained but does not validate PostgreSQL
locking, isolation, or production pooling behavior.
