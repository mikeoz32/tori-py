# In-Memory Task API

This tutorial walks through the tested Task API in
[`examples/tori_py/reference_apps/task_api/app.py`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/reference_apps/task_api/app.py).
It is a compact example of one Tori Py HTTP application, not a production task
service and not a generated project template.

## Prepare The Checkout

Run commands from the repository root. Synchronize the workspace and the CLI
extra without changing project dependencies:

```text
uv sync --all-packages --all-groups --extra cli
```

The three useful source files are:

| File | Purpose |
| --- | --- |
| [`app.py`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/reference_apps/task_api/app.py) | Models, repository, service, HTTP pipeline, modules, and bootstrap |
| [`README.md`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/reference_apps/task_api/README.md) | Short run instructions and declared boundaries |
| [`test_task_api_reference.py`](https://github.com/mikeoz32/tori-py/blob/main/packages/tori-py/tests/docs/test_task_api_reference.py) | HTTP behavior, settings bootstrap, provider override, and lifecycle verification |

## Read The Architecture From The Inside Out

Although the example is kept in one file for inspection, its responsibilities
are separated by types and modules.

| Layer | Source | Responsibility |
| --- | --- | --- |
| Contracts and configuration | [`TaskApiSettings`, `CreateTask`, and `Task`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/reference_apps/task_api/app.py#L40-L57) | Typed settings, incoming command shape, and outgoing task representation |
| Infrastructure | [`TaskRepository`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/reference_apps/task_api/app.py#L67-L100) | In-memory task identity and storage plus lifecycle cleanup |
| Application | [`TaskService`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/reference_apps/task_api/app.py#L102-L128) | Title normalization, business validation, repository calls, and logging |
| HTTP policy | [`TaskWriteGuard` and `TaskErrorFilter`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/reference_apps/task_api/app.py#L137-L169) | Educational write policy and domain-error translation |
| HTTP adapter | [`TaskController`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/reference_apps/task_api/app.py#L171-L203) | Route declarations, request bindings, and response shape |
| Composition | [module declarations and factory](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/reference_apps/task_api/app.py#L206-L263) | Provider ownership, visibility, pipeline registration, and ASGI export |

The controller depends on `TaskService`, not on storage. `TaskService` depends on
the repository, typed settings, and logger. The repository knows nothing about
HTTP. This separation lets an adapter translate transport input and failures
without putting request objects in the application layer.

## Understand The Request Model

The API exposes three routes:

| Request | Input | Success |
| --- | --- | --- |
| `GET /tasks` | None | `200` with a JSON list of tasks |
| `POST /tasks` | JSON `{"title":"..."}` and `X-Task-Write: allow` | `201` with the task, request marker, and request ID |
| `GET /tasks/{task_id}` | Integer path value | `200` with one task |

`Body()` and `Path()` initially bind transport values. An annotation alone does
not convert them. The global `MsgspecValidationPipe` converts the body to
`CreateTask` and the path segment to `int`. A body such as `{"title":3}` fails
with `400` before the controller runs.

Shape conversion is not the complete business rule. `TaskService.create()`
strips surrounding whitespace, rejects an empty result, and enforces
`TaskApiSettings.max_title_length`. The default is 120 characters. Keeping this
rule in the service means direct service callers cannot bypass it by avoiding
HTTP.

`Task` is a frozen msgspec struct, so the repository and HTTP response share a
small immutable application value rather than exposing a mutable storage row.

## Follow A Create Request

A successful `POST /tasks` crosses these boundaries:

```text
open one Tori Py request scope and partial request context
  -> Starlette route match
  -> TaskWriteGuard checks X-Task-Write
  -> bind the raw JSON body, RequestMarker, and RequestContext
  -> MsgspecValidationPipe converts the body to CreateTask
  -> TaskController calls TaskService
  -> TaskService normalizes and validates the title
  -> TaskRepository assigns the ID and stores the task
  -> ordinary return value is encoded as JSON with status 201
  -> close the request scope
```

Guards run before body binding. A missing or different `X-Task-Write` value
therefore produces the framework's `403` response without invoking the service.
The guard is an authorization-shaped extension point, not authentication.

`RequestMarker` is supplied by a request-scoped `FactoryProvider`. It is created
lazily for a `POST /tasks` request only when that request reaches argument
binding and resolves the `Inject()` parameter. Each such create request gets a
separate instance even though this demonstration gives every instance the same
visible value, `request-scope`. Other routes and create requests rejected by the
guard do not resolve it. `RequestContext` is supplied by the Starlette adapter
and carries the accepted or generated request ID. `Context()` and `Inject()`
parameters do not pass through pipes.

For domain failures, `TaskErrorFilter` maps `TaskNotFound` to `404` and
`TaskTitleInvalid` to `400` Problem Details. It re-raises every unknown error so
the framework can sanitize it. Msgspec conversion errors and guard denial use
the framework's normal HTTP error rendering.

See [Request Pipeline](../pipeline/index.md) for the complete stage order and
[Pipes and Validation](../pipeline/pipes-and-validation.md) for conversion
semantics.

## Compose The Modules

The composition section demonstrates all three explicit provider forms used by
the application:

| Module | Owns | Exports or visibility |
| --- | --- | --- |
| `SettingsModule.for_root(...)` | One `TaskApiSettings` value decoded from configured sources | Declared global for graph-wide settings injection |
| `LoggingModule.for_root(...)` | The application logger integration | Imported by the root composition |
| `InfrastructureModule` | Singleton `TaskRepository` class provider | Exports `TaskRepository` |
| `TasksModule` | `TaskService`, guard value, request marker factory, and `TaskController` | Imports repository infrastructure; providers remain feature-local |
| `AppModule` | Global validation pipe and task error filter | Imports the complete graph and re-exports `TaskRepository` |

The repository is declared once by `InfrastructureModule`. `TasksModule` imports
that module to make the exported repository visible to `TaskService`.
`AppModule` also imports the infrastructure module directly so the root can
re-export the repository as an explicit testing boundary. Tori Py compiles these
declarations into one graph; it does not scan the package or create providers
from annotations automatically.

The settings descriptor uses the application file's directory as its base
directory. The CLI can add a non-secret bootstrap override before that deferred
module materializes. For example:

```text
uv run tori-py run examples.tori_py.reference_apps.task_api.app:create_application --set max_title_length=40
```

For more detail on ownership and visibility, read [Modules](../fundamentals/modules.md)
and [Providers and DI](../fundamentals/providers-and-di.md).

## Bootstrap And Run

`create_application()` compiles `AppModule` with a fresh `StarletteAdapter`, then
adds the already-visible validation and error-filter tokens to the global
pipeline. It returns an unstarted `NestApplication`.

The final line exports `application = asgi(create_application)`. That wrapper
lets an ASGI server own exact startup and shutdown through lifespan. Do not start
the application inside the factory.

Run the local convenience server:

```text
uv run tori-py run examples.tori_py.reference_apps.task_api.app:create_application
```

In another PowerShell session, exercise the routes:

```powershell
'{"title":"  Read Tori Py guides  "}' | curl.exe -X POST "http://127.0.0.1:8000/tasks" -H "content-type: application/json" -H "x-task-write: allow" -H "x-request-id: task-tutorial" --data-binary '@-'
curl.exe "http://127.0.0.1:8000/tasks"
curl.exe "http://127.0.0.1:8000/tasks/1"
curl.exe "http://127.0.0.1:8000/tasks/999"
```

The first response includes the normalized title, `marker: "request-scope"`,
and `request_id: "task-tutorial"`. Stop the server normally so ASGI lifespan can
invoke application shutdown and `TaskRepository.on_module_destroy()`.

The exported wrapper can also be hosted directly:

```text
uv run uvicorn examples.tori_py.reference_apps.task_api.app:application --lifespan on
```

Use direct Uvicorn when server host, port, proxy, worker, reload, or timeout
options are required. See [CLI and ASGI Hosting](../operations/cli-and-asgi.md).

## Run And Read The Tests

Run the exact tested specification:

```text
uv run pytest packages/tori-py/tests/docs/test_task_api_reference.py -q
```

The [first test](https://github.com/mikeoz32/tori-py/blob/main/packages/tori-py/tests/docs/test_task_api_reference.py#L15-L57)
starts a production application, checks guard denial, title normalization,
request ID propagation, list/get behavior, Problem Details, and body validation,
then shuts down in `finally`.

The [settings test](https://github.com/mikeoz32/tori-py/blob/main/packages/tori-py/tests/docs/test_task_api_reference.py#L60-L74)
establishes `BootstrapContext` before factory compilation and proves that a
four-character maximum reaches `TaskService`.

The [override test](https://github.com/mikeoz32/tori-py/blob/main/packages/tori-py/tests/docs/test_task_api_reference.py#L77-L97)
targets the exported `TaskRepository` in its exact owner module. It compiles
through `TestingModule`, uses the production pipeline and Starlette adapter, and
closes the testing application. This verifies behavior without changing a
private provider or maintaining a separate test container.

## Production Limitations

This example intentionally omits production concerns:

- Tasks, IDs, and the next-ID counter live in one process and disappear on
  shutdown. Every worker would have independent state.
- The repository is a simple dictionary, not a durable, concurrent persistence
  design. There are no transactions, migrations, constraints, backups, or
  reconciliation.
- `X-Task-Write: allow` is a fixed educational check. There is no identity,
  credential verification, object authorization, rate limit, or audit policy.
- There is no idempotency key. A repeated create request can create another
  task, and caller timeout cannot establish whether a side effect occurred.
- There is no pagination, deletion, update, readiness policy, metrics backend,
  or production deployment configuration.
- `CreateTask` demonstrates a minimal body model; a public contract would need
  deliberate unknown-field and schema-evolution policy.

To replace memory with application-owned persistence, continue with the
[SQLAlchemy guide](../techniques/sqlalchemy/index.md) and its tested Task API
listed in the [examples catalog](../reference/examples.md#http-reference-applications).
To publish a documented contract, continue with [OpenAPI](../openapi/index.md).
