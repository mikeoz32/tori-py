# Distributed Task API Tutorial Source

This directory contains the executable Part 3 tutorial source. It preserves the
HTTP contract while splitting the application into three independently composed
roots:

- `gateway` exposes `POST /tasks`, `GET /tasks`, and `GET /tasks/{task_id}`.
- `tasks` owns the in-memory repository, local CQRS handlers, and task RPC API.
- `audit` consumes the versioned `task-created` integration event and
  deduplicates it by `event_id`.

Run the system test from the repository root:

```text
uv run pytest examples/tori_py/tutorials/distributed_task_api/task_app/test_system.py -q
```

The test runs three separate Tori Py applications over one process-local
`InMemoryBroker`. This proves the application, DI, RPC, CQRS, and event-consumer
boundaries. It does not prove RabbitMQ durability, process isolation, failover,
or production delivery behavior.

The task service writes first and then directly awaits event publication. That
sequence is intentionally not an outbox: a failure between the write and publish
can leave a task without a corresponding audit event. A production design that
requires atomic persistence and eventual publication needs an application-owned
transactional outbox and relay.
