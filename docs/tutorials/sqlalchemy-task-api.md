# Persist the Task API with SQLAlchemy

This tutorial continues [Part 1: Build a Task API](task-api.md) in the same
`task-api` project. It replaces the in-memory repository with
[SQLAlchemy](../techniques/sqlalchemy/index.md), so tasks are stored in a SQLite
database and survive a restart. Alembic migrations create the database schema.

It branches from Part 1 rather than following Part 2. The later parts keep the
in-memory repository so that each part can focus on one technique; this
tutorial changes only persistence.

The continuity rules are:

- the REST API is unchanged: same routes, payloads, and Problem Details;
- one route is new: `POST /tasks/batch` creates several tasks or none;
- `TaskService` keeps its title rules, and its methods become `async` because
  database calls are asynchronous;
- the application never creates tables itself; migrations are a separate step.

## What You Will Build

| Feature | Technique |
| --- | --- |
| Database URL from settings and the environment | `SettingsModule` and `SqlAlchemyModule.for_root_async()` |
| A table for tasks | A SQLAlchemy declarative model |
| Reads and writes | A repository registered with `SqlAlchemyModule.for_feature()` |
| One transaction per call | Automatic repository transactions |
| All-or-nothing batch creation | `EntityManager.transaction()` |
| Schema changes | Alembic migrations |
| Tests on a real database | `TestingModule.replace_module()` with `SqlAlchemyModule.for_engine()` |

## Continue In The Part 1 Project

Open the `task-api` directory you completed in Part 1. Add the SQLAlchemy
integration from the same checkout, the async SQLite driver, and Alembic as a
development tool:

```text
uv add --editable "../tori-py/packages/tori-py-sqlalchemy"
uv add aiosqlite
uv add --dev alembic
```

`tori-py-sqlalchemy` installs SQLAlchemy. The URL scheme selects the driver:
`sqlite+aiosqlite://` here, or `postgresql+asyncpg://` after `uv add asyncpg`.

When this tutorial is complete, the project has this shape:

```text
task-api/
  alembic.ini         new
  migrations/         new
    env.py
    script.py.mako
    versions/
      0001_create_tasks.py
  task_app/
    __init__.py       package marker
    models.py         add one request body
    settings.py       new
    database.py       new
    state.py          replace
    services.py       replace
    http.py           replace
    app.py            replace
    test_app.py       replace
```

## Step 1: Read The Database URL From Settings

Create `task_app/settings.py`:

```python
--8<-- "examples/tori_py/tutorials/sqlalchemy_task_api/task_app/settings.py"
```

`TaskApiSettings` is a typed [settings](../techniques/settings.md) model. The
default URL points to `tasks.db` in the current directory. The `TASK_API_`
prefix maps environment variables onto fields, with `__` between nested names:

```text
TASK_API_DATABASE__URL=sqlite+aiosqlite:///other.db
```

`SETTINGS_OPTIONS` is a module-level value because the application and the
Alembic environment in Step 7 read the same settings.

## Step 2: Define The Table

Create `task_app/database.py`:

```python
--8<-- "examples/tori_py/tutorials/sqlalchemy_task_api/task_app/database.py"
```

`TaskRow` is the database model. The HTTP API keeps returning the `Task` value
from Part 1, so the table can change without changing the JSON contract.
`String(120)` matches the title rule in `TaskService`.

`SqlAlchemyModule.for_root_async()` builds its options with a factory. ToriPy
injects the factory's `settings` parameter by its annotation from the imported
settings module. The resulting root module creates the async engine during
startup and disposes it during shutdown. It is global by default and exports
`EntityManager`, so other modules can inject it without importing the root.

## Step 3: Replace The Repository

Replace `task_app/state.py`:

```python
--8<-- "examples/tori_py/tutorials/sqlalchemy_task_api/task_app/state.py"
```

`@repository(TaskRow)` binds the class to the model, and `Repository[TaskRow]`
supplies `add()`, `get()`, `find()`, `count()`, and the other operations listed
in [Repositories](../techniques/sqlalchemy/repositories.md). `all_ordered()` adds
one query of its own through the protected `_scalars()` helper.

`SqlAlchemyModule.for_feature()` registers `TaskRepository` as a singleton
provider whose token is the class itself. The repository holds no session.
Each call outside an explicit transaction opens a session, commits or rolls
back, and closes the session.

## Step 4: Make The Service Asynchronous

Add a request body for the batch route to `task_app/models.py`:

```python
--8<-- "examples/tori_py/tutorials/sqlalchemy_task_api/task_app/models.py"
```

Replace `task_app/services.py`:

```python
--8<-- "examples/tori_py/tutorials/sqlalchemy_task_api/task_app/services.py"
```

`create()`, `get()`, and `all()` keep the Part 1 behavior. Each repository call
runs in its own transaction, so a created task is committed when `create()`
returns. The service converts every row to a `Task` before returning it: the
session is closed by then, and a detached row cannot load anything more.

`create_many()` wraps several calls in `EntityManager.transaction()`. Inside the
`async with` block, repository calls in the same task share one session and one
transaction. `add()` flushes, so each row has its `id` before the block ends. If
any title is invalid, `TaskTitleInvalid` leaves the block, the transaction rolls
back, and no task from the batch is stored. A database error has the same
effect. [Transactions](../techniques/sqlalchemy/transactions.md) describes
nesting, savepoints, and the rule against sharing a transaction with child
tasks.

## Step 5: Await The Service In The Controller

Replace `task_app/http.py`:

```python
--8<-- "examples/tori_py/tutorials/sqlalchemy_task_api/task_app/http.py"
```

The handlers were already `async`; they now await the service. The new
`POST /tasks/batch` route uses the same validation pipe and error filter as the
other routes, so an invalid title in a batch returns the same Problem Details
response.

## Step 6: Compose The Application

Replace `task_app/app.py`:

```python
--8<-- "examples/tori_py/tutorials/sqlalchemy_task_api/task_app/app.py"
```

The SQLAlchemy root replaces Part 1's `InfrastructureModule`, and
`TasksModule` imports the `task_persistence` feature module that provides
`TaskRepository`. The global pipe and filter are the same providers as in
Part 1. They are now named in a `PipelineOptions` value passed to
`NestApplication.create()`, so the tests in Step 9 can apply the same pipeline.

## Step 7: Create The Schema With Alembic

Generate the Alembic project files from the `task-api` root:

```text
uv run alembic init -t async migrations
```

This creates `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`,
and an empty `migrations/versions/` directory. Keep `script.py.mako`, delete the
generated `migrations/README`, and replace `alembic.ini` with a shorter file
that holds no database URL:

```ini
--8<-- "examples/tori_py/tutorials/sqlalchemy_task_api/alembic.ini"
```

`prepend_sys_path` makes `task_app` importable from `migrations/env.py`. Replace
`migrations/env.py`:

```python
--8<-- "examples/tori_py/tutorials/sqlalchemy_task_api/migrations/env.py"
```

The environment loads `TaskApiSettings` with `load_settings()`, so migrations
use the same file, environment, and default values as the application.
`target_metadata` gives Alembic the tables declared on `Base`.

Generate the first revision:

```text
uv run alembic revision --autogenerate --rev-id 0001 -m "create tasks"
```

Autogenerate compares `Base.metadata` with the database that the URL selects and
writes `migrations/versions/0001_create_tasks.py`. Review every generated
revision before committing it: autogenerate does not detect every change, such
as a renamed column. The tutorial's copy, rewritten with current Python type
syntax, is:

```python
--8<-- "examples/tori_py/tutorials/sqlalchemy_task_api/migrations/versions/0001_create_tasks.py"
```

Apply it:

```text
uv run alembic upgrade head
```

The integration never creates or migrates tables during startup. Run
`alembic upgrade head` as a deployment step before starting a new version.
[Testing and Migrations](../techniques/sqlalchemy/testing-and-migrations.md#alembic-migrations)
covers dependency groups and deployment images.

## Step 8: Run The Application

Start the server from the `task-api` root:

```text
uv run tori-py run task_app.app:create_application
```

Create tasks, then try a batch with one invalid title and a valid batch:

=== "PowerShell"

    ```powershell
    '{"title":"  Ship the database  "}' | curl.exe --silent --show-error -X POST "http://127.0.0.1:8000/tasks" -H "content-type: application/json" --data-binary '@-'
    '{"titles":["Plan the release","   "]}' | curl.exe --silent --show-error -X POST "http://127.0.0.1:8000/tasks/batch" -H "content-type: application/json" --data-binary '@-'
    '{"titles":["Plan the release","Write notes"]}' | curl.exe --silent --show-error -X POST "http://127.0.0.1:8000/tasks/batch" -H "content-type: application/json" --data-binary '@-'
    curl.exe --silent --show-error "http://127.0.0.1:8000/tasks"
    ```

=== "Bash"

    ```bash
    curl --silent --show-error -X POST "http://127.0.0.1:8000/tasks" \
      -H "content-type: application/json" \
      --data '{"title":"  Ship the database  "}'
    curl --silent --show-error -X POST "http://127.0.0.1:8000/tasks/batch" \
      -H "content-type: application/json" \
      --data '{"titles":["Plan the release","   "]}'
    curl --silent --show-error -X POST "http://127.0.0.1:8000/tasks/batch" \
      -H "content-type: application/json" \
      --data '{"titles":["Plan the release","Write notes"]}'
    curl --silent --show-error "http://127.0.0.1:8000/tasks"
    ```

The first batch returns `400` with the title Problem Details and stores
nothing. The final list on a new database is:

```json
[{"id":1,"title":"Ship the database"},{"id":2,"title":"Plan the release"},{"id":3,"title":"Write notes"}]
```

SQLite gives the next row the ID that the rolled-back insert used. PostgreSQL
sequences do not reuse IDs, so the same requests there leave a gap.

Stop the server with `Ctrl+C` and start it again: `GET /tasks` returns the same
tasks. Delete `tasks.db` and run `uv run alembic upgrade head` to start with an
empty database.

## Step 9: Test Against A Real Database

Replace `task_app/test_app.py`:

```python
--8<-- "examples/tori_py/tutorials/sqlalchemy_task_api/task_app/test_app.py"
```

`application_on()` creates an engine for a new SQLite file in the test's
temporary directory and creates the tables from `Base.metadata`.
`replace_module()` swaps the settings-driven root for
`SqlAlchemyModule.for_engine(engine)`, so the application uses that engine and
never reads `TASK_API_DATABASE__URL`. `for_engine()` does not own the engine;
the helper disposes it after closing the application. `compile()` receives the
same `PIPELINE` as `create_application()`.

The tests check that:

1. the Part 1 HTTP contract holds on the database: Problem Details, validation
   errors, IDs, ordering, and `404`;
2. a batch with an invalid title stores nothing, and a valid batch stores every
   task;
3. `alembic upgrade head` creates exactly the schema that `Base.metadata`
   describes, and `create_application()` works against the migrated database
   through `TASK_API_DATABASE__URL`.

The third test runs the Alembic command line in a subprocess, as a deployment
would. It is the reason the first two tests may create tables directly from the
metadata.

Run them:

```text
uv run pytest task_app/test_app.py -q
```

Expected result: `3 passed`.

## Guarantees And Limits

- **SQLite is local.** One SQLite file serves one machine and allows one writer
  at a time. Use PostgreSQL with `asyncpg` for several processes or replicas.
- **Transactions are per call unless you ask.** Two repository calls in a row
  are two transactions. Use `EntityManager.transaction()` whenever several
  writes must succeed or fail together.
- **Titles are not unique.** As in Part 1, two tasks may have the same title.
  A unique constraint would need a new migration and a `409` mapping in the
  error filter.
- **Batches are unbounded.** `POST /tasks/batch` accepts any number of titles.
  Limit the list length before exposing the route.
- **Migrations are explicit.** A database without the `tasks` table fails at the
  first query with a server error. Run `alembic upgrade head` before starting
  the application.
- **Rows stay inside the service.** Return values such as `Task`, not ORM rows,
  from services and controllers.

## Next Steps

- [SQLAlchemy Configuration](../techniques/sqlalchemy/configuration.md): engine
  and session options, named roots, and existing engines.
- [Repositories](../techniques/sqlalchemy/repositories.md): every repository
  operation and `EntityManager` used directly.
- [Transactions](../techniques/sqlalchemy/transactions.md): savepoints, locks,
  and task ownership.
- [Testing and Migrations](../techniques/sqlalchemy/testing-and-migrations.md):
  provider overrides and Alembic in deployments.
