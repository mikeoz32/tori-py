# OpenAPI Task API Tutorial Source

This directory contains the executable source for the OpenAPI Task API tutorial.
It continues the Part 1 Task API without changing its existing routes, serves an
OpenAPI 3.1 document at `/openapi.json` and Swagger UI at `/docs`, describes
error responses as Problem Details, and adds `DELETE /tasks/{task_id}`, which a
demonstration bearer guard protects.

The dependency delta from Part 1 is `tori-py-openapi`.

Run the tests from the repository root:

```text
uv run pytest examples/tori_py/tutorials/openapi_task_api/task_app/test_app.py -q
uv run ruff check examples/tori_py/tutorials/openapi_task_api
uv run ruff format --check examples/tori_py/tutorials/openapi_task_api
uv run ty check examples/tori_py/tutorials/openapi_task_api/task_app
```

Expected result: `5 passed`.

Run the application and open `http://127.0.0.1:8000/docs`:

```text
uv run tori-py run examples.tori_py.tutorials.openapi_task_api.task_app.app:create_application
```

`DELETE /tasks/{task_id}` accepts `Authorization: Bearer tutorial-admin-token`.
The fixed token is a demonstration, not an authentication system.
