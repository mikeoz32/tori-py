# Authenticate and Audit Tutorial Source

This directory contains the executable source for the authentication and audit
tutorial. It continues the Part 1 Task API with request-pipeline components of
its own:

- `MaintenanceMiddleware`, registered globally, answers `503` while
  `TASK_API_MAINTENANCE=on`;
- `AuthenticationGuard`, registered on each controller, turns an optional bearer
  token into a request-scoped principal;
- `RequireUser` and `RequireAdmin`, registered on routes, authorize the caller;
- `AuditInterceptor`, registered on `POST /tasks`, records each create in the
  audit log that `GET /audit` returns to administrators.

Reads stay public, and `POST /tasks` needs a token. `models.py`, `state.py`, and
`services.py` are unchanged from Part 1, and no package is added.
`DemoTokenVerifier` accepts the fixed demonstration tokens `alice-token`
(administrator) and `bob-token`.

Run the tests from the repository root:

```text
uv run pytest examples/tori_py/tutorials/pipeline_auth_task_api/task_app/test_app.py -q
uv run ruff check examples/tori_py/tutorials/pipeline_auth_task_api
uv run ruff format --check examples/tori_py/tutorials/pipeline_auth_task_api
uv run ty check examples/tori_py/tutorials/pipeline_auth_task_api/task_app
```

Expected result: `6 passed`.

Run the application:

```text
uv run tori-py run examples.tori_py.tutorials.pipeline_auth_task_api.task_app.app:create_application
```
