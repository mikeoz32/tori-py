# Build a Task API: Part 1

This tutorial builds a complete ToriPy HTTP application from an empty directory.
It is Part 1 of a three-part series that evolves one Task API from an ordinary
layered application, through CQRS, into a distributed system without changing
the shared HTTP contract.

Every Python file shown here is complete. The page includes those files from the
tested source under `examples/tori_py/tutorials/task_api/task_app`, so the
tutorial code and its executable tests stay aligned. You do not need an existing
application or a generated project.

## What You Will Build

The application exposes three endpoints:

| Request | Input | Success response |
| --- | --- | --- |
| `POST /tasks` | JSON `{"title":"..."}` | `201` with `{"id":1,"title":"..."}` |
| `GET /tasks` | None | `200` with a JSON list of tasks |
| `GET /tasks/{task_id}` | Integer path value | `200` with one task or `404` |

The successful HTTP representation is deliberately direct. A task is exactly
`{"id": int, "title": str}`: there is no command status, projection status,
request marker, actor, or other architecture metadata. The API requires no
custom headers. A POST needs only the standard `Content-Type: application/json`
header.

The application has four boundaries:

```text
HTTP request
  -> TaskController                     transport adapter
  -> TaskService                        application behavior
  -> TaskRepository                     in-memory infrastructure
  -> Task                               response value
```

The title is trimmed and must contain 1-120 characters. State remains in memory
for the life of one application process.

## Prerequisites

You need Python `>=3.14,<3.15` and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/). Basic knowledge
of Python packages and `async`/`await` is sufficient.

The initial `0.1.0` package train is not published on PyPI yet. Clone ToriPy and
create the tutorial application beside the checkout so `uv` can install the
framework from an explicit editable source:

```text
git clone https://github.com/mikeoz32/tori-py.git
uv init --python 3.14 --bare task-api
cd task-api
uv python pin 3.14
```

`uv init --bare` creates `pyproject.toml`. `uv python pin` creates
`.python-version` with the interpreter pin. Replace the generated project
metadata with this exact supported range:

```toml
[project]
name = "task-api"
version = "0.1.0"
requires-python = ">=3.14,<3.15"
dependencies = []
```

Add the framework and test tools from the sibling checkout:

```text
uv add --editable "../tori-py/packages/tori-py[cli,testing]"
uv add --dev pytest pytest-asyncio
```

The `cli` extra supplies Uvicorn and the `tori-py run` command. The `testing`
extra supplies HTTPX for in-process ASGI requests. `uv add` records the editable
framework dependency and creates `uv.lock`. After the package train is
published, an application can replace the editable path with a normal registry
requirement.

## Create the Project Structure

Create this package and these files inside `task-api`:

```text
task-api/
  .python-version
  pyproject.toml
  uv.lock
  task_app/
    __init__.py
    models.py
    state.py
    services.py
    http.py
    app.py
    test_app.py
```

Add the package marker in `task_app/__init__.py`:

```python
--8<-- "examples/tori_py/tutorials/task_api/task_app/__init__.py"
```

The package uses relative imports, so the same source works as the top-level
`task_app` package in this project and as the tested package in the ToriPy
checkout. Each remaining file has one primary responsibility.

## Step 1: Define the HTTP Values and Application Errors

Create `task_app/models.py`:

```python
--8<-- "examples/tori_py/tutorials/task_api/task_app/models.py"
```

`CreateTaskBody` is the untrusted request-body shape. It requires a string
`title` and rejects unknown fields instead of silently accepting transport data
that the application does not understand.

`Task` is the response value stored by the repository. It is frozen, so callers
cannot mutate repository state through a returned task. Msgspec can encode both
values directly, but only `Task` is returned by the HTTP contract.

`TaskTitleInvalid` and `TaskNotFound` are application errors. They contain no
HTTP status codes or Starlette objects; the HTTP adapter will decide how to
represent them.

## Step 2: Add In-Memory State

Create `task_app/state.py`:

```python
--8<-- "examples/tori_py/tutorials/task_api/task_app/state.py"
```

`TaskRepository` owns task identity and storage. IDs start at 1, increase after
each successful create, and the list is returned in ID order. `get()` translates
the dictionary's `KeyError` into the application-level `TaskNotFound` error, so
callers do not depend on the storage representation.

This repository is intentionally synchronous because every operation is an
immediate in-memory operation with no `await` point. A database repository would
have a different resource and transaction boundary, but the service should not
need to know its table layout or driver API.

## Step 3: Implement Application Behavior

Create `task_app/services.py`:

```python
--8<-- "examples/tori_py/tutorials/task_api/task_app/services.py"
```

`TaskService` is the application boundary used by HTTP. Its constructor asks for
`TaskRepository`; module composition will supply the concrete provider.

Creation strips surrounding whitespace and then enforces the 1-120 character
rule. This validation belongs in the service rather than only in the controller
or a pipe, so a direct service caller cannot bypass it. Shape conversion and
business validity are separate concerns: msgspec proves that `title` is a
string, while `TaskService` decides which normalized strings are accepted.

Read methods delegate to the repository and return application values. The
service knows nothing about request objects, JSON, status codes, or Problem
Details.

## Step 4: Adapt HTTP to the Service

Create `task_app/http.py`:

```python
--8<-- "examples/tori_py/tutorials/task_api/task_app/http.py"
```

`@controller("/tasks")` provides the route prefix. `@post`, `@get`, and
`@status(201)` declare the public method, path, and create status. The controller
injects `TaskService`, not `TaskRepository`, and returns `Task` values directly.

### Raw Binding and Validation

`Body()` and `Path("task_id")` are binding metadata. They first select raw
transport values: the decoded JSON body and the path string. Python annotations
alone do not perform runtime conversion.

The global `MsgspecValidationPipe` added in the next step uses the annotations to
convert those values:

- the body becomes `CreateTaskBody`;
- `task_id` becomes `int`;
- a missing `title`, a non-string title, or an unknown body field fails before
  the controller runs;
- a path such as `/tasks/not-an-integer` fails before `TaskService.get()` runs.

Malformed JSON fails during body binding. Binding and conversion failures use
the framework's standard `400` Problem Details response.

### Application Error Filter

`TaskErrorFilter` translates only the two expected application errors.
`TaskTitleInvalid` becomes `400`; `TaskNotFound` becomes `404`. The response
includes the request path as its Problem Details `instance`.

The final `raise error` is important. Unknown failures are not mislabeled as
client mistakes and are not exposed by this filter. Re-raising lets another
filter or the framework's sanitized fallback handle them.

## Step 5: Compose Modules and Bootstrap

Create `task_app/app.py`:

```python
--8<-- "examples/tori_py/tutorials/task_api/task_app/app.py"
```

The modules make ownership and visibility explicit:

| Module | Owns | Visibility |
| --- | --- | --- |
| `InfrastructureModule` | One singleton `TaskRepository` provider | Exports `TaskRepository` to importing modules |
| `TasksModule` | `TaskService` and `TaskController` | Imports infrastructure; feature providers remain private |
| `AppModule` | Validation-pipe and error-filter values | Imports the complete task feature |

`InfrastructureModule` declares the repository exactly once. Exporting its token
does not move ownership; it permits `TasksModule` to resolve the repository when
constructing `TaskService`. `TasksModule` owns the service and controller because
they implement the task feature. `AppModule` assembles that feature with
application-wide HTTP policy.

ToriPy compiles these declarations into one dependency graph. It does not scan
the package or register classes merely because their constructors have type
annotations. Invalid dependencies or module visibility fail during composition
instead of on the first matching request.

`ValueProvider` gives stable tokens to the pipe and filter. After compilation,
`create_application()` installs those tokens globally, so every controller route
uses the same conversion and error policy.

The factory returns an unstarted `NestApplication`. The exported
`application = asgi(create_application)` wrapper lets an ASGI server own exact
startup and shutdown through lifespan. Do not call `start()` inside the factory:
the host starts the compiled application once and shuts it down on normal server
termination.

## Step 6: Run the Application

Start the convenience development server from the `task-api` project root:

```text
uv run tori-py run task_app.app:create_application
```

The CLI loads the async factory and drives application lifecycle. To use Uvicorn
options directly, host the exported ASGI wrapper instead:

```text
uv run uvicorn task_app.app:application --lifespan on --reload
```

Keep either server running and use another terminal for the requests below. Stop
it normally with `Ctrl+C` so lifespan shutdown runs.

### Create and Read Tasks

The following commands send only the standard JSON content type on POST. No
application-specific header is required.

=== "PowerShell"

    ```powershell
    curl.exe --silent --show-error "http://127.0.0.1:8000/tasks"
    '{"title":"  Ship Part 1  "}' | curl.exe --silent --show-error -X POST "http://127.0.0.1:8000/tasks" -H "content-type: application/json" --data-binary '@-'
    curl.exe --silent --show-error "http://127.0.0.1:8000/tasks"
    curl.exe --silent --show-error "http://127.0.0.1:8000/tasks/1"
    ```

=== "Bash"

    ```bash
    curl --silent --show-error "http://127.0.0.1:8000/tasks"
    curl --silent --show-error -X POST "http://127.0.0.1:8000/tasks" \
      -H "content-type: application/json" \
      --data '{"title":"  Ship Part 1  "}'
    curl --silent --show-error "http://127.0.0.1:8000/tasks"
    curl --silent --show-error "http://127.0.0.1:8000/tasks/1"
    ```

In command order, the exact JSON values are:

```json
[]
```

```json
{"id":1,"title":"Ship Part 1"}
```

```json
[{"id":1,"title":"Ship Part 1"}]
```

```json
{"id":1,"title":"Ship Part 1"}
```

The POST status is `201`; every GET above is `200`. The response title is
trimmed, and the POST response is the task itself rather than an envelope.

### Inspect Problem Details

Send an invalid title and request an absent task:

=== "PowerShell"

    ```powershell
    '{"title":"   "}' | curl.exe --silent --show-error -X POST "http://127.0.0.1:8000/tasks" -H "content-type: application/json" --data-binary '@-'
    curl.exe --silent --show-error "http://127.0.0.1:8000/tasks/999"
    ```

=== "Bash"

    ```bash
    curl --silent --show-error -X POST "http://127.0.0.1:8000/tasks" \
      -H "content-type: application/json" \
      --data '{"title":"   "}'
    curl --silent --show-error "http://127.0.0.1:8000/tasks/999"
    ```

The invalid POST returns `400` with
`Content-Type: application/problem+json` and this exact JSON value:

```json
{"type":"about:blank","title":"Bad Request","status":400,"detail":"After trimming, the task title must contain 1-120 characters.","instance":"/tasks"}
```

The absent GET returns `404` with
`Content-Type: application/problem+json` and this exact JSON value:

```json
{"type":"about:blank","title":"Not Found","status":404,"detail":"Task was not found.","instance":"/tasks/999"}
```

JSON whitespace is insignificant; the keys and values above are the complete
response bodies.

## Step 7: Test the Service and HTTP Contract

Create `task_app/test_app.py`:

```python
--8<-- "examples/tori_py/tutorials/task_api/task_app/test_app.py"
```

Run the complete file:

```text
uv run pytest task_app/test_app.py -q
```

Expected result:

```text
2 passed
```

The first test constructs `TaskService` and `TaskRepository` directly. It proves
normalization, the title limits, identity allocation, ordered reads, and missing
task behavior without involving HTTP or the dependency-injection container.

The second test starts the production application, sends real ASGI requests
through the controller and pipeline, and always calls shutdown in `finally`. It
checks:

- the empty, create, list, and get success contract;
- the direct `201` task body with no architecture metadata;
- title errors and missing-task Problem Details;
- malformed JSON;
- missing and unknown body fields;
- invalid integer path conversion.

`http_client()` uses HTTPX with an in-process ASGI transport. It exercises
application routing, binding, validation, DI, filters, and lifecycle without a
network socket. It does not test Uvicorn, TCP, TLS, reverse proxies, workers, or
operating-system signal delivery.

## Understand the Runtime Flow

Application startup follows this shape:

```text
ASGI host begins lifespan startup
  -> call create_application()
  -> compile AppModule and its imports
  -> register the InfrastructureModule repository provider
  -> make the exported repository visible to TasksModule
  -> validate and construct the application graph
  -> install the global validation pipe and error filter
  -> start the NestApplication
  -> admit HTTP requests
```

A successful create request follows this shape:

```text
open one HTTP request scope
  -> match POST /tasks
  -> Body() binds the decoded raw JSON value
  -> MsgspecValidationPipe converts it to CreateTaskBody
  -> resolve TaskController with TaskService
  -> TaskService trims and validates the title
  -> TaskRepository assigns an ID and stores Task
  -> encode Task directly as JSON with status 201
  -> close the request scope
```

For a business failure, the same pipeline raises `TaskTitleInvalid` or
`TaskNotFound`; `TaskErrorFilter` converts it to Problem Details before the
request scope closes. For conversion failures, the framework's validation error
handling produces Problem Details before the controller is called.

On normal server termination, the ASGI wrapper stops request admission and
shuts down the application. This Part 1 repository owns no external connection,
but preserving the lifespan boundary matters when later versions add buses,
brokers, database pools, or other managed resources.

## Guarantees and Limitations

While one application process remains running, this tutorial guarantees:

- `POST /tasks` returns `201` with the created task directly;
- surrounding title whitespace is removed and normalized length is 1-120;
- successful creates receive increasing integer IDs beginning at 1;
- `GET /tasks` returns tasks in ID order and `GET /tasks/{id}` returns one task;
- body and path values are converted before the controller runs;
- expected application failures use the documented Problem Details contract;
- provider ownership and cross-module visibility are explicit;
- tests exercise the service and the production HTTP composition.

It deliberately does not provide:

- durable storage, transactions, migrations, constraints, or backups;
- shared state between processes or Uvicorn workers;
- a concurrency strategy for threads or multiple writers;
- update, completion, deletion, pagination, or search endpoints;
- authentication, authorization, rate limiting, or audit history;
- create idempotency or a way to resolve an indeterminate client timeout;
- OpenAPI publication, deployment configuration, metrics, or tracing;
- CQRS buses, domain-event delivery, RPC, or distributed consistency.

Restarting the process loses all tasks and resets the next ID to 1. Running
multiple workers creates multiple independent repositories, so requests can
observe different task lists. The in-memory repository is a learning adapter,
not a production persistence design.

## Part 1 Checkpoint

You now have a complete layered application with a stable public contract:

```text
models -> repository -> service -> HTTP adapter -> explicit modules -> ASGI
```

The important boundary is not the number of files. HTTP owns binding and error
representation, the service owns task rules, infrastructure owns state, and
modules own providers and visibility. Tests pin the contract before the internal
architecture evolves.

Continue to [Part 2: evolve the same Task API with CQRS](cqrs-application.md).
Part 2 preserves `POST 201`, direct `{"id","title"}` responses, the GET routes,
and the absence of special headers while replacing direct controller-to-service
calls with commands and queries and adding asynchronous event observers.
