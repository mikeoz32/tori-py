# Persistent Stream Task Activity Tutorial Source

This directory contains the executable source for the persistent stream task
activity tutorial. It continues the Part 1 Task API without changing its HTTP
contract. After each create, the service publishes a `TaskCreatedV1` record to a
two-partition persistent stream; a stream handler builds an activity read model
served at `GET /activity`, and `GET /streams/health` reports the stream runtime.

`models.py` and `state.py` are unchanged from Part 1. The dependency delta is
`tori-py-persistent-streams-core`, `tori-py-persistent-streams`, and
`tori-py-persistent-streams-rabbitmq`.

Run the tests from the repository root. They use the in-memory adapter:

```text
uv run pytest examples/tori_py/tutorials/stream_task_activity/task_app/test_app.py -q
uv run ruff check examples/tori_py/tutorials/stream_task_activity
uv run ruff format --check examples/tori_py/tutorials/stream_task_activity
uv run ty check examples/tori_py/tutorials/stream_task_activity/task_app
```

Expected result: `5 passed`.

Run the application with the in-memory adapter:

```text
uv run tori-py run examples.tori_py.tutorials.stream_task_activity.task_app.app:create_application
```

Run against RabbitMQ Streams with Docker Compose. Set `TASK_API_STREAMS=rabbitmq`
in the shell that starts the application:

```text
docker compose -f examples/tori_py/tutorials/stream_task_activity/compose.yaml up -d --wait
uv run python -m examples.tori_py.tutorials.stream_task_activity.task_app.smoke
docker compose -f examples/tori_py/tutorials/stream_task_activity/compose.yaml down -v
```

The smoke check runs the application twice against the broker and confirms that
the second process rebuilds the activity read model from the stream.
