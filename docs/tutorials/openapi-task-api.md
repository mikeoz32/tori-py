# Document the Task API with OpenAPI

This tutorial continues [Part 1: Build a Task API](task-api.md) in the same
`task-api` project. It adds [OpenAPI](../openapi/index.md) documentation: an
OpenAPI 3.1 document at `/openapi.json` and Swagger UI at `/docs`, both
generated from the same compiled routes that serve requests.

It branches from Part 1 rather than following Part 2, so the controller stays
small and every decorator is easy to see.

The continuity rules are:

- the existing routes are unchanged: same paths, payloads, and Problem Details;
- one route is new: `DELETE /tasks/{task_id}`, protected by a bearer token, so
  the document has a security requirement to describe;
- documentation never changes runtime behavior: the validation pipe validates
  requests, and a guard, not the document, enforces the token.

## What You Will Build

| Feature | Technique |
| --- | --- |
| `/openapi.json` and `/docs` | `OpenApiModule.for_root()` |
| Grouped, named operations | `@api_tags`, `@api_operation`, and docstrings |
| Documented error responses | Problem Details models and `@api_response` |
| A protected route | A guard for enforcement and `@api_security` for the document |
| An empty `204` response | An explicit `HttpResponse` and `@api_response(204)` |
| A document that stays accurate | Tests for the document and for the error model |

## Continue In The Part 1 Project

Open the `task-api` directory you completed in Part 1 and add the OpenAPI
integration from the same checkout:

```text
uv add --editable "../tori-py/packages/tori-py-openapi"
```

When this tutorial is complete, the package has this shape:

```text
task-api/
  task_app/
    __init__.py       package marker
    models.py         replace
    state.py          add delete()
    services.py       add delete()
    http.py           replace
    app.py            replace
    test_app.py       replace
```

## Step 1: Serve The Generated Document

The integration is a module. Importing its root into `AppModule` is enough to
serve a document:

```python
from tori_py_openapi import OpenApiInfo, OpenApiModule, OpenApiOptions

openapi_module = OpenApiModule.for_root(
    OpenApiOptions(info=OpenApiInfo(title="Task API", version="1.0.0"))
)
```

Without any other change, `/openapi.json` already describes the three Part 1
routes. The integration reads paths, the `task_id` path parameter, the request
body, the `201` status, and the `Task` and `CreateTaskBody` schemas from the
compiled routes:

```json
{
  "operationId": "TaskController_create",
  "requestBody": {"required": true, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreateTaskBody"}}}},
  "responses": {"201": {"description": "Created", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Task"}}}}}
}
```

What it cannot read from the code is everything the error filter and the
service decide at runtime: the `400` and `404` responses, their Problem Details
bodies, and which callers may call a route. The next steps add that.

## Step 2: Describe The Error Body

Replace `task_app/models.py`:

```python
--8<-- "examples/tori_py/tutorials/openapi_task_api/task_app/models.py"
```

`Problem` matches the Problem Details body that ToriPy and `TaskErrorFilter`
return. Validation failures add an `errors` object; `msgspec.UNSET` keeps that
field optional without making it nullable, so the schema lists it as an
optional property.

`msgspec.Meta(description=...)` on `title` adds a schema description. It
carries no constraint, so validation is unchanged: the service still trims the
title and enforces 1-120 characters.

## Step 3: Add The Delete Operation

Add `delete()` to `TaskRepository` in `task_app/state.py`:

```python
--8<-- "examples/tori_py/tutorials/openapi_task_api/task_app/state.py"
```

Add the matching method to `TaskService` in `task_app/services.py`:

```python
--8<-- "examples/tori_py/tutorials/openapi_task_api/task_app/services.py"
```

## Step 4: Annotate The Controller

Replace `task_app/http.py`:

```python
--8<-- "examples/tori_py/tutorials/openapi_task_api/task_app/http.py"
```

The decorators only attach metadata; none of them registers a route or changes
how a request runs.

- `@api_tags("tasks")` on the controller groups every operation under one tag.
- `@api_operation` sets a summary and a stable `operation_id`. Client generators
  turn operation IDs into method names, so choose them once and keep them.
- A route docstring becomes the operation description. Text after `\f` stays in
  the code and out of the document.
- `@api_response(400, model=Problem, media_type=PROBLEM_JSON)` documents a
  response the integration cannot infer. Declare it on each route that can
  return it: `GET /tasks` has no input to reject, so it has no `400`.

The delete route shows how security is split:

- `@use_guard(AdminTokenGuard)` enforces the token at runtime. Without the
  expected `Authorization` header the guard denies the request, and ToriPy
  returns `403` Problem Details.
- `@api_security("admin")` only tells readers and clients that the operation
  needs the `admin` scheme. It enforces nothing. A route with `@api_security`
  and no guard is open.

A `204` response has no body. The integration therefore requires the handler to
return an explicit empty `HttpResponse` and the route to declare
`@api_response(204, ...)`. Returning `None` does not produce `204`: an ordinary
route encodes it as JSON `null`.

`ADMIN_TOKEN` is a fixed value so the tutorial stays self-contained. A real
service validates a signed token from an identity provider; see
[Security and Swagger UI](../openapi/security-and-swagger.md).

## Step 5: Configure The Document And Swagger UI

Replace `task_app/app.py`:

```python
--8<-- "examples/tori_py/tutorials/openapi_task_api/task_app/app.py"
```

`OpenApiOptions` sets the document title, version, and description, and
declares the `admin` bearer scheme that `@api_security("admin")` refers to.
`bearer_format=None` omits `bearerFormat`, because the token is not a JWT.
`persistAuthorization` keeps a token entered in Swagger UI across page reloads.

The integration generates the document once during startup and serves the same
bytes for every request. An invalid annotation or conflicting metadata stops
startup instead of producing a wrong document.

By default `/docs` loads Swagger UI from a pinned CDN with Subresource Integrity
hashes. A deployment with a strict Content Security Policy must allow those
origins or host the assets itself; see
[Swagger UI deployment](../openapi/security-and-swagger.md#swagger-ui-deployment).

## Step 6: Run And Explore

Start the server from the `task-api` root:

```text
uv run tori-py run task_app.app:create_application
```

Open `http://127.0.0.1:8000/docs`. The page lists the four operations under
**tasks**, shows the `400`, `403`, and `404` Problem Details responses, and marks
**Delete a task** with a lock. Select **Authorize**, enter
`tutorial-admin-token`, and try the delete operation.

The same calls from a terminal:

=== "PowerShell"

    ```powershell
    '{"title":"Remove me"}' | curl.exe --silent --show-error -X POST "http://127.0.0.1:8000/tasks" -H "content-type: application/json" --data-binary '@-'
    curl.exe --silent --show-error -X DELETE "http://127.0.0.1:8000/tasks/1" --write-out "`nHTTP %{http_code}`n"
    curl.exe --silent --show-error -X DELETE "http://127.0.0.1:8000/tasks/1" -H "authorization: Bearer tutorial-admin-token" --write-out "HTTP %{http_code}`n"
    ```

=== "Bash"

    ```bash
    curl --silent --show-error -X POST "http://127.0.0.1:8000/tasks" \
      -H "content-type: application/json" \
      --data '{"title":"Remove me"}'
    curl --silent --show-error -X DELETE "http://127.0.0.1:8000/tasks/1" \
      --write-out "\nHTTP %{http_code}\n"
    curl --silent --show-error -X DELETE "http://127.0.0.1:8000/tasks/1" \
      -H "authorization: Bearer tutorial-admin-token" \
      --write-out "HTTP %{http_code}\n"
    ```

The first delete returns `403` with a Problem Details body. The second returns
`204` with no body.

## Step 7: Test The Document

Replace `task_app/test_app.py`:

```python
--8<-- "examples/tori_py/tutorials/openapi_task_api/task_app/test_app.py"
```

The two Part 1 tests are unchanged and prove that the existing contract still
holds. The new tests check that:

1. the document has the expected operation IDs, tags, response codes, Problem
   Details content, security on the delete operation only, and the `admin`
   scheme, and that `/docs` serves Swagger UI;
2. the delete route rejects a missing or wrong token with `403`, deletes with
   the right token, and returns `404` for a missing task;
3. every documented error response decodes as `Problem`, so the hand-written
   model cannot drift from what the server sends.

Run them:

```text
uv run pytest task_app/test_app.py -q
```

Expected result: `5 passed`.

## Guarantees And Limits

- **The document does not validate.** `MsgspecValidationPipe` converts and
  validates requests. Without it, handlers would receive raw values whatever
  the schema says.
- **The document does not enforce security.** The guard does. Keep
  `@api_security` and the guard together on every protected route.
- **Error responses are declared by hand.** The integration cannot see what a
  filter returns. The model test catches a changed body, but a new error status
  needs a new `@api_response`.
- **Operation IDs are a contract.** Renaming one breaks generated clients.
- **The token is a demonstration.** Do not ship a fixed token.
- **The documentation routes are public.** Anyone who can reach the server can
  read `/openapi.json` and `/docs`.
  [Protecting documentation routes](../openapi/security-and-swagger.md#protecting-documentation-routes)
  shows how to restrict them.

## Next Steps

- [OpenAPI Configuration](../openapi/configuration.md): document and Swagger UI
  paths, servers, and Swagger UI options.
- [Metadata and Responses](../openapi/metadata-and-responses.md): every
  decorator, response headers, and excluded routes.
- [Schemas and Routes](../openapi/schemas-and-routes.md): parameters, bodies,
  unions, and supported model types.
- [Advanced OpenAPI Usage](../openapi/advanced.md): startup diagnostics and
  testing documentation.
