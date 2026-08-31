# CQRS Task API Tutorial Source

This directory is the executable source shown by
[`docs/tutorials/cqrs-application.md`](../../../../docs/tutorials/cqrs-application.md).
The tutorial presents the project as a fresh consumer application named
`task_app`; the additional parent packages only let the same files run inside
this repository.

Run the tests from the repository root:

```text
uv run pytest examples/tori_py/tutorials/cqrs_task_api/task_app/test_app.py -q
```

Expected result: `2 passed`.

Run the HTTP application:

```text
uv run tori-py run examples.tori_py.tutorials.cqrs_task_api.task_app.app:create_application
```

`POST /tasks` returns `202` with the normalized task and an
`asynchronous-in-process` projection marker. Stop the server normally so ASGI
lifespan can drain and close the CQRS buses.
