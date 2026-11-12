# SQLAlchemy Task API Tutorial Source

This directory contains the executable source for the SQLAlchemy Task API
tutorial. It continues the Part 1 Task API without changing its HTTP contract,
stores tasks in SQLite through async SQLAlchemy and `aiosqlite`, adds an atomic
`POST /tasks/batch` route, and creates the schema with Alembic migrations.

The dependency delta from Part 1 is `tori-py-sqlalchemy`, `aiosqlite`, and the
development dependency `alembic`. `alembic.ini` and `migrations/` sit beside
`task_app`, as they do at the root of the tutorial project.

Run the tests from the repository root:

```text
uv run pytest examples/tori_py/tutorials/sqlalchemy_task_api/task_app/test_app.py -q
uv run ruff check examples/tori_py/tutorials/sqlalchemy_task_api
uv run ruff format --check examples/tori_py/tutorials/sqlalchemy_task_api
uv run ty check examples/tori_py/tutorials/sqlalchemy_task_api
```

Expected result: `3 passed`.

Apply the migrations and run the application from the repository root:

```text
uv run alembic -c examples/tori_py/tutorials/sqlalchemy_task_api/alembic.ini upgrade head
uv run tori-py run examples.tori_py.tutorials.sqlalchemy_task_api.task_app.app:create_application
```

Both commands use `sqlite+aiosqlite:///tasks.db`, which creates `tasks.db` in
the current directory. Set `TASK_API_DATABASE__URL` to use another database, and
delete `tasks.db` to start again with an empty database.
