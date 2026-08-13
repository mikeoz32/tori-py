# Task API

The Task API is a small in-memory reference application at
`examples/tori_py/reference_apps/task_api/`. It demonstrates explicit module
composition rather than a production task-management product.

It includes typed settings, an in-memory repository provider, request scope,
an authorization-shaped guard, Msgspec validation, a domain error filter,
provider overrides, direct ASGI export, and the CLI factory path.

Run it from the repository root:

```text
uv sync --all-packages --all-groups --extra cli
uv run tori-py run examples.tori_py.reference_apps.task_api.app:create_application
```

The application is intentionally limited to in-memory storage and a fake policy.
It does not provide persistent storage or authentication.
