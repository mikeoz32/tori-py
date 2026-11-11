# Live Task Board Tutorial Source

This directory contains the executable source for the Live Task Board tutorial.
It continues the Part 2 CQRS Task API without changing its HTTP contract and
adds a server-rendered `/board` page. The page creates tasks through the
`CommandBus`, reads them through the `QueryBus`, and shows them in a
browser-owned LiveView stream. A `TaskCreated` event handler wakes every
connected board, so tasks created in another tab or through `POST /tasks`
appear without a reload.

The dependency delta from Part 2 is `tori-py-liveview` and
`tori-py-liveview-ui`.

Run the tests from the repository root:

```text
uv run pytest examples/tori_py/tutorials/live_task_board/task_app/test_app.py -q
uv run ruff check examples/tori_py/tutorials/live_task_board
uv run ruff format --check examples/tori_py/tutorials/live_task_board
uv run ty check examples/tori_py/tutorials/live_task_board/task_app
```

Expected result: `6 passed`.

Run the application and open `http://127.0.0.1:8000/board` in two tabs:

```text
uv run tori-py run examples.tori_py.tutorials.live_task_board.task_app.app:create_application
```

The page uses a development token secret unless `TASK_BOARD_SECRET` is set.
Set a strong value of at least 32 bytes outside local development.

## Browser Test

Install Chromium once and run the explicit browser test:

```text
uv run playwright install chromium
uv run pytest examples/tori_py/tutorials/live_task_board/task_app/browser_e2e.py
```

It drives two tabs with the official Phoenix clients: live title validation,
task creation, the cleared input, a REST-created task reaching both tabs, and
the newest-first order. The file is named outside normal pytest discovery so the
browser install stays an explicit step.
