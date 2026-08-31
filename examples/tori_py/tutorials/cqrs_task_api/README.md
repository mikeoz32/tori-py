# Task API Tutorial Source, Part 2: CQRS

This directory contains the executable source for Part 2, which continues the
ordinary Task API from Part 1 without changing its HTTP contract. Commands and
queries now pass through CQRS buses, while reads still use the same
repository-backed `TaskService`. `TaskCreated` events fan out asynchronously to
audit and metrics observers.

The Part 2 dependency delta is `tori-py-cqrs-core` and `tori-py-cqrs`; the Tori
Py framework, msgspec, and test dependencies from Part 1 are unchanged.

Run the tests from the repository root:

```text
uv run pytest examples/tori_py/tutorials/cqrs_task_api/task_app/test_app.py -q
uv run ruff check examples/tori_py/tutorials/cqrs_task_api
uv run ruff format --check examples/tori_py/tutorials/cqrs_task_api
uv run ty check examples/tori_py/tutorials/cqrs_task_api/task_app
```

Expected result: `3 passed`.

Run the HTTP application:

```text
uv run tori-py run examples.tori_py.tutorials.cqrs_task_api.task_app.app:create_application
```

`POST /tasks` returns `201` with the normalized task directly. Reads are
immediately available from the repository; audit and metrics event reactions
remain asynchronous. Stop the server normally so ASGI lifespan can drain and
close the CQRS buses.
