# Authenticate and Audit the Task API

This tutorial continues [Part 1: Build a Task API](task-api.md) in the same
`task-api` project. It adds your own components to the
[request pipeline](../pipeline/index.md): a middleware that switches the API into
maintenance mode, a guard that identifies the caller from a bearer token, guards
that decide what the caller may do, and an interceptor that audits writes. Each
one is registered at the level where it belongs: for the whole application, for
a controller, or for one route.

The continuity rules are:

- `GET /tasks` and `GET /tasks/{task_id}` are unchanged and stay public;
- `POST /tasks` now needs `Authorization: Bearer <token>`; with a valid token,
  its payloads and Problem Details are as in Part 1;
- one route is new: `GET /audit` returns the audit log to administrators;
- `models.py`, `state.py`, and `services.py` stay exactly as in Part 1.

## What You Will Build

A `POST /tasks` request passes through these stages:

```text
MaintenanceMiddleware        global middleware        503 during maintenance
└─▶ AuthenticationGuard      controller guard         who is calling?        401 for a bad token
    └─▶ RequireUser          route guard              is anyone signed in?   401
        └─▶ body binding, validation pipe   global pipe                      400
            └─▶ AuditInterceptor           route interceptor   records the outcome
                └─▶ TaskController.create
an escaping error ─▶ TaskErrorFilter (global filter) ─▶ default Problem Details
```

| Component | Kind | Level | Purpose |
| --- | --- | --- | --- |
| `MaintenanceMiddleware` | Middleware | Global | Answer `503` before anything else runs |
| `AuthenticationGuard` | Guard | Controller | Turn an optional bearer token into a principal |
| `RequireUser` | Guard | Route | Require a signed-in caller |
| `RequireAdmin` | Guard | Route | Require the `admin` role |
| `AuditInterceptor` | Interceptor | Route | Record who called and whether it succeeded |
| `validation` | Pipe | Global | Validate bodies and paths, as in Part 1 |
| `task-errors` | Filter | Global | Map task errors to Problem Details, as in Part 1 |

## Continue In The Part 1 Project

Open the `task-api` directory you completed in Part 1. Every component in this
tutorial uses the `tori-py` package you already installed, so there is nothing
to add.

When this tutorial is complete, the project has this shape:

```text
task-api/
  task_app/
    __init__.py       package marker
    models.py         unchanged
    state.py          unchanged
    services.py       unchanged
    auth.py           new
    audit.py          new
    maintenance.py    new
    http.py           replace
    app.py            replace
    test_app.py       replace
```

## Step 1: Identify The Caller

Create `task_app/auth.py`:

```python
--8<-- "examples/tori_py/tutorials/pipeline_auth_task_api/task_app/auth.py"
```

`Principal` is the caller as the application sees it: a name and roles.
`TokenVerifier` is the boundary to whatever issues tokens. `DemoTokenVerifier`
knows two fixed tokens, `alice-token` for an administrator and `bob-token` for
an ordinary user. That is only for this tutorial: a real verifier validates a
signed token, such as a JWT, from an identity provider. Because the rest of the
code depends on the `TokenVerifier` Protocol, replacing the verifier changes
nothing else.

The work is split in two, as
[Authorization and Errors](../recipes/authorization-and-errors.md#authentication-boundary)
recommends:

- **Authentication** answers who is calling. `AuthenticationGuard` reads the
  `Authorization` header. Without one, the caller is anonymous and the request
  continues. With a valid bearer token, the caller is that token's principal. Any
  other value is rejected with `401` and `WWW-Authenticate: Bearer
  error="invalid_token"`, even on a public route, because the client sent
  credentials that do not work.
- **Authorization** answers whether that caller may do this. `RequireUser`
  rejects anonymous callers with `401` and `WWW-Authenticate: Bearer`.
  `RequireAdmin` returns `False` for a caller without the `admin` role, and the
  framework answers `403` with the detail `Forbidden.`.

A guard that returns `False` always produces that standard `403`. To choose
another status, detail, or header, a guard raises `HttpException`, as
`CurrentPrincipal.require()` does for `401`.

`CurrentPrincipal` carries the caller from the guard to later stages of the same
request. It is a request-scoped provider: the framework creates one per request,
and every component of that request that injects it gets the same instance.
`AuthenticationGuard` binds it once, and the other components only read it.
[Values Established by Guards](../http/context-and-injection.md#values-established-by-guards)
describes this pattern.

`AuthenticationGuard` takes a `RequestContext` because it reads a Starlette
request header. The other guards accept the transport-neutral `ExecutionContext`
and do not use it.

## Step 2: Audit Writes

Create `task_app/audit.py`:

```python
--8<-- "examples/tori_py/tutorials/pipeline_auth_task_api/task_app/audit.py"
```

An interceptor wraps the handler. `AuditInterceptor` calls `next()` once, which
runs the handler, and records an `AuditEntry` in `finally`, so a handler that
raises is recorded as `failed`. `context.route_id` identifies the route, for
example `POST /tasks`.

Interceptors run after guards, argument binding, and pipes. A request rejected
by a guard or by body validation therefore never reaches `AuditInterceptor`; the
log holds only requests that reached the handler. A create with a blank title
does reach it, because the service rejects the title, and is recorded as
`failed`. Record rejected requests in the guard if you need them too.

`AuditInterceptor` injects the request-scoped `CurrentPrincipal`, so it must be
request-scoped itself. `AuditLog` is a singleton shared by all requests.

## Step 3: Add Maintenance Mode

Create `task_app/maintenance.py`:

```python
--8<-- "examples/tori_py/tutorials/pipeline_auth_task_api/task_app/maintenance.py"
```

Middleware wraps everything after it, including the guards. When
`MaintenanceMode` is enabled, `MaintenanceMiddleware` returns `503` with
`Retry-After: 60` without calling `next()`, so no guard, pipe, interceptor, or
handler runs. A request with an invalid token gets `503`, not `401`.

`MaintenanceMode.from_environment()` reads `TASK_API_MAINTENANCE` once, when the
application starts. Middleware is registered only by provider token, so Step 5
declares a provider for it.

## Step 4: Register The Components On The Controllers

Replace `task_app/http.py`:

```python
--8<-- "examples/tori_py/tutorials/pipeline_auth_task_api/task_app/http.py"
```

`@use_guard(AuthenticationGuard)` on a controller class applies to every route
of that controller. Both controllers use it, so every task and audit request has
a bound `CurrentPrincipal`.

Decorators on a method apply to that route only:

- `create()` adds `RequireUser` and `AuditInterceptor`; the two read routes add
  nothing and stay public.
- `list_entries()` adds `@use_guards(RequireUser, RequireAdmin)`. Guards run in
  the order listed, after the controller guard, and the first rejection stops
  the rest, so an anonymous caller gets `401` from `RequireUser` rather than
  `403` from `RequireAdmin`.

Use one decorator per pipeline kind on each target, with every component in one
ordered call. `TaskErrorFilter` is the Part 1 filter. It re-raises the
`HttpException` from a guard, and the default renderer turns it into Problem
Details with its status, title, and headers.

## Step 5: Compose The Application

Replace `task_app/app.py`:

```python
--8<-- "examples/tori_py/tutorials/pipeline_auth_task_api/task_app/app.py"
```

`AuthModule` owns authentication. `CurrentPrincipal` and the three guards are
request-scoped: the guards inject `CurrentPrincipal`, and a singleton cannot
depend on a request-scoped provider. `AuthModule` exports the guards because the
controllers in `TasksModule` resolve them from their own module's visibility. It
exports `TokenVerifier` so that a test can replace it; a test can override only
exported providers.

`AuditModule` provides the log and the interceptor. `AppModule` provides the
global components, and `PIPELINE` registers them:

| Stage | Global | Controller | Route |
| --- | --- | --- | --- |
| Middleware | `MaintenanceMiddleware` | | |
| Guards | | `AuthenticationGuard` | `RequireUser`, `RequireAdmin` |
| Pipes | `validation` | | |
| Interceptors | | | `AuditInterceptor` |
| Filters | `task-errors` | | |

Part 1 registered the pipe and filter with `use_global_pipe()` and
`use_global_filter()` after creating the application. Middleware has no such
method, so all three now go into `PipelineOptions`, which `NestApplication.create()`
receives. Global tokens resolve from `AppModule`.

## Step 6: Run It

Start the server from the `task-api` root:

```text
uv run tori-py run task_app.app:create_application
```

Create a task without a token and with Bob's token, then read the audit log as
Bob and as Alice:

=== "PowerShell"

    ```powershell
    '{"title":"Plan"}' | curl.exe --silent --show-error --include -X POST "http://127.0.0.1:8000/tasks" -H "content-type: application/json" --data-binary '@-'
    '{"title":"Plan"}' | curl.exe --silent --show-error -X POST "http://127.0.0.1:8000/tasks" -H "content-type: application/json" -H "Authorization: Bearer bob-token" --data-binary '@-'
    curl.exe --silent --show-error "http://127.0.0.1:8000/audit" -H "Authorization: Bearer bob-token"
    curl.exe --silent --show-error "http://127.0.0.1:8000/audit" -H "Authorization: Bearer alice-token"
    ```

=== "Bash"

    ```bash
    curl --silent --show-error --include -X POST "http://127.0.0.1:8000/tasks" \
      -H "content-type: application/json" --data '{"title":"Plan"}'
    curl --silent --show-error -X POST "http://127.0.0.1:8000/tasks" \
      -H "content-type: application/json" -H "Authorization: Bearer bob-token" \
      --data '{"title":"Plan"}'
    curl --silent --show-error "http://127.0.0.1:8000/audit" \
      -H "Authorization: Bearer bob-token"
    curl --silent --show-error "http://127.0.0.1:8000/audit" \
      -H "Authorization: Bearer alice-token"
    ```

The first create returns `401` with `www-authenticate: Bearer`. The second
returns the task. Bob gets `403` from `/audit`, and Alice gets one entry:
`{"actor":"bob","route":"POST /tasks","outcome":"succeeded"}`.

To try maintenance mode, stop the server and start it again with the variable
set:

=== "PowerShell"

    ```powershell
    $env:TASK_API_MAINTENANCE = "on"
    uv run tori-py run task_app.app:create_application
    ```

=== "Bash"

    ```bash
    TASK_API_MAINTENANCE=on uv run tori-py run task_app.app:create_application
    ```

Every route now returns `503` with `retry-after: 60`. In PowerShell, run
`Remove-Item Env:TASK_API_MAINTENANCE` before the next start.

## Step 7: Test It

Replace `task_app/test_app.py`:

```python
--8<-- "examples/tori_py/tutorials/pipeline_auth_task_api/task_app/test_app.py"
```

The tests check that:

1. the Part 1 service behaves as before;
2. the Part 1 HTTP contract holds when the caller sends Bob's token;
3. writes without a token get `401` with `WWW-Authenticate: Bearer`, and a
   wrong token, a non-bearer scheme, or an empty token gets `401` with
   `error="invalid_token"`, on reads too;
4. only administrators read the audit log, which records Bob's successful and
   failed creates but not the anonymous attempt that a guard rejected;
5. in maintenance mode, the middleware answers `503` before the guards, even for
   a wrong token;
6. a test can replace `TokenVerifier` without touching the guards.

The maintenance test sets the environment variable with `monkeypatch` before it
creates the application. The last test replaces the exported `TokenVerifier`
with `override_provider(..., module=AuthModule)`, which is how to test against an
identity source of your own.

Run them:

```text
uv run pytest task_app/test_app.py -q
```

Expected result: `6 passed`.

## Guarantees And Limits

- **Not an identity system.** Tori Py provides the guard and the request scope,
  not token issuing or validation. Replace `DemoTokenVerifier`, keep tokens out
  of source code, and send them only over HTTPS.
- **Reads are public.** Only routes with `RequireUser` need a token. A route you
  add to `TaskController` later is public until you add a guard.
- **The audit log is partial and temporary.** It lives in memory and records
  only requests that reach the handler.
- **Maintenance mode is read at startup.** Changing it needs a restart.
- **HTTP only.** WebSocket gateways, microservice handlers, and stream handlers
  have their own pipelines; HTTP middleware and these guards do not apply to
  them. See [Other transports](../recipes/authorization-and-errors.md#other-transports).
- **No CORS, CSRF, or rate limiting.** The framework does not provide them.

## Next Steps

- [Middleware and Guards](../pipeline/middleware-and-guards.md),
  [Interceptors and Filters](../pipeline/interceptors-and-filters.md), and
  [Ordering and Cancellation](../pipeline/ordering-and-cancellation.md): the
  complete pipeline contract.
- [Authorization and Errors](../recipes/authorization-and-errors.md): policy
  providers and safe error mapping.
- [Document the Task API with OpenAPI](openapi-task-api.md): describe a bearer
  scheme with `api_security`.
