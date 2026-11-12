# WebSocket Task Feed Tutorial Source

This directory contains the executable source for the WebSocket task feed
tutorial. It continues the Part 1 Task API without changing its HTTP contract
and adds `WS /tasks/live`: after connecting, a client receives a snapshot of
the current tasks and then one message for every task created afterwards.

`models.py`, `state.py`, and `http.py` are unchanged from Part 1. There is no
new dependency: WebSocket gateways are part of `tori-py-framework`.

Run the tests from the repository root:

```text
uv run pytest examples/tori_py/tutorials/websocket_task_feed/task_app/test_app.py -q
uv run ruff check examples/tori_py/tutorials/websocket_task_feed
uv run ruff format --check examples/tori_py/tutorials/websocket_task_feed
uv run ty check examples/tori_py/tutorials/websocket_task_feed/task_app
```

Expected result: `5 passed`.

Run the application from the repository root:

```text
uv run tori-py run examples.tori_py.tutorials.websocket_task_feed.task_app.app:create_application
```

Then open `http://127.0.0.1:8000/tasks` in a browser and run this in the
developer console:

```javascript
const feed = new WebSocket("ws://127.0.0.1:8000/tasks/live");
feed.onmessage = (event) => console.log(JSON.parse(event.data));
```

Create tasks with `POST /tasks` from another terminal and watch them arrive.
