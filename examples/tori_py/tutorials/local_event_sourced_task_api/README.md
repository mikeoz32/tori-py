# One-Process Event Sourcing Tutorial Source

This directory contains the executable source for the one-process event sourcing
tutorial. It continues the Part 2 CQRS Task API without changing its existing
HTTP contract. Tasks are stored as events in `InMemoryEventStore`; a projection
over the store's global order serves the reads, and `PATCH /tasks/{task_id}`
renames a task, guarded by `ETag` and `If-Match`.

The tests cover the aggregate, an upcaster from schema version 1, optimistic
concurrency, and an indeterminate commit. `testing.py` holds the test stores that
reproduce the last two. The dependency delta is
`tori-py-cqrs-event-sourcing-core` and `tori-py-cqrs-event-sourcing`.

Run the tests from the repository root:

```text
uv run pytest examples/tori_py/tutorials/local_event_sourced_task_api/task_app -q
uv run ruff check examples/tori_py/tutorials/local_event_sourced_task_api
uv run ruff format --check examples/tori_py/tutorials/local_event_sourced_task_api
uv run ty check examples/tori_py/tutorials/local_event_sourced_task_api/task_app
```

Expected result: `8 passed`.

Run the application:

```text
uv run tori-py run examples.tori_py.tutorials.local_event_sourced_task_api.task_app.app:create_application
```
