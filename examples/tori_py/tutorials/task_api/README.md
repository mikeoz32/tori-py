# Task API Tutorial Source

This directory contains the executable source for Part 1, the ordinary Task API.
The `task_app` directory can also be copied and used as a top-level Python
package because its internal imports are relative.

Run the repository verification commands from the repository root:

```text
uv run pytest examples/tori_py/tutorials/task_api/task_app/test_app.py -q
uv run ruff check examples/tori_py/tutorials/task_api
uv run ruff format --check examples/tori_py/tutorials/task_api
uv run ty check examples/tori_py/tutorials/task_api/task_app
```

Run the HTTP application from the repository root:

```text
uv run tori-py run examples.tori_py.tutorials.task_api.task_app.app:create_application
```
