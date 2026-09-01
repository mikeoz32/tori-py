# Event-Sourced Task API Tutorial Source

This directory is the complete executable Part 4 snapshot. It composes four
independent Tori Py application roots:

- `gateway` exposes the HTTP API and calls two finite-deadline typed RPC APIs.
- `tasks` owns task commands, local CQRS, the event store, and direct stream
  publication after commit.
- `projection` consumes task records and exposes projection-only RPC reads.
- `audit` consumes the same records in an independent consumer group.

The command handler registers one `after_commit` callback. That callback publishes
the committed event directly to the stream and is awaited before a successful
command response is returned. Projection and audit consumers still run
asynchronously, so a successful `POST` or `PATCH` does not imply that
projection-backed `GET` requests have converged.

Part 4 intentionally replaces the Part 3 task RPC identity with
`tutorial.task-commands.v1` and adds `tutorial.task-projection.v1`. This is a
coordinated client/server cutover, not a backward-compatible rolling upgrade.
Deploy callers and the matching service identities together or provide an
application-owned compatibility bridge outside this snapshot.

RPC and stream delivery are not exactly once. A gateway `502` or `504` does not
prove that a command was never executed. In particular, do not blindly retry a
timed-out `POST`: its first execution may have committed and allocated an ID.
Use an application-level idempotency key and durable deduplication before making
automatic retries safe.

Run the focused snapshot tests from the repository root:

```text
uv run pytest examples/tori_py/tutorials/event_sourced_task_api/task_app -q
```

The system test uses four production composition roots with `TestingModule`
replacements. RPC runs over one `InMemoryBroker`; persistent streams run over
application-owned handles to one `InMemoryPersistentLog`. This proves the
application boundaries and deterministic eventual consistency, not RabbitMQ
durability, failover, restart safety, process isolation, or exactly-once
processing.

## RabbitMQ

Start the educational RabbitMQ 4.1 broker:

```text
docker compose -f examples/tori_py/tutorials/event_sourced_task_api/compose.yaml up -d
```

In separate terminals, start the stream-only audit service, projection service,
command service, and HTTP gateway:

```text
uv run python -m examples.tori_py.tutorials.event_sourced_task_api.task_app.audit.app
uv run python -m examples.tori_py.tutorials.event_sourced_task_api.task_app.projection.app
uv run python -m examples.tori_py.tutorials.event_sourced_task_api.task_app.tasks.app
uv run uvicorn examples.tori_py.tutorials.event_sourced_task_api.task_app.gateway.app:application
```

The defaults use the explicitly educational `tutorial` / `tutorial` broker
credentials. Override `RABBITMQ_URL`, `RABBITMQ_STREAM_HOST`,
`RABBITMQ_STREAM_PORT`, `RABBITMQ_USER`, or `RABBITMQ_PASSWORD` as needed.

The Compose healthcheck proves only that the RabbitMQ node responds. It does not
prove that native Streams topology exists or that any Tori Py application is
ready. For this tutorial, wait for RabbitMQ and its Stream plugin, start audit
and projection and wait for each application startup to complete, then start the
task command service, and expose the gateway last. Each Tori Py startup barrier
covers only resources owned by that process; there is no cross-process
readiness coordinator or service health endpoint in this snapshot.

## State, Retention, and Shutdown

The command event store, integer ID allocator, projection, audit log, and external
consumer checkpoints are process-local memory. A restart loses the corresponding
state. Consumer checkpoints starting from `Beginning` can rebuild projection or
audit only while every required record is still retained. A retention gap blocks
a partition; this example has no repair or snapshot procedure.

Do not retain `tutorial-task-events-v1` while restarting with an empty command
event store and reset ID allocator. New aggregate IDs and versions can collide
semantically with retained records. That combination is incompatible and
requires a coordinated reset of the command store, physical stream, consumer
checkpoints, projection, and audit state, or replacement with durable stores and
an explicit migration plan.

Direct publication is deliberately a simple dual write, not an outbox. If the
event-store commit succeeds but stream publication is not confirmed, the RPC
returns `command_committed_finalization_failed`; the stored event remains
committed and this snapshot has no retry or reconciliation worker. These
limitations are why this tutorial must not be treated as restart-safe or
exactly-once infrastructure.
