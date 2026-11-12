# Publish Task Activity to a Persistent Stream

This tutorial continues [Part 1: Build a Task API](task-api.md) in the same
`task-api` project. After each task is created, the application publishes a
record to a [persistent stream](../techniques/persistent-streams/index.md). A
stream handler in the same application reads the stream and builds an activity
read model. You develop and test with the in-memory adapter, then run the same
code against RabbitMQ Streams in Docker.

It branches from Part 1 rather than following Part 2. [Part 4: Add Event
Sourcing](event-sourced-application.md) uses persistent streams between several
processes; this tutorial stays in one process so that each stream concept gets
its own step.

The continuity rules are:

- the existing routes are unchanged: same paths, payloads, and Problem Details;
- two routes are new: `GET /activity` returns the read model, and
  `GET /streams/health` reports the stream runtime;
- `models.py` and `state.py` stay exactly as in Part 1; `TaskService.create()`
  becomes `async` because publishing is asynchronous.

## What You Will Build

```text
POST /tasks ─▶ TaskService.create ─▶ TaskRepository (task saved)
                       │
                       └─▶ TaskActivityPublisher ─▶ stream "task-activity"
                                                     partitions 0 and 1
                                                            │
GET /activity ◀── ActivityLog ◀── ActivityProjection.apply ◀┘
                                  consumer group "task-activity-log-v1"
```

| Feature | Technique |
| --- | --- |
| A versioned record | A `msgspec` struct and a codec |
| Ordering per task | A partition key resolver |
| Typed publishing | A publisher `Protocol` with `@stream_publish` |
| Knowing whether a record was stored | `PublishReceipt.outcome` |
| A read model | `@stream_handler` with a consumer group |
| Safe redelivery | Records keyed by record ID |
| Restart behavior | Checkpoints stored with the read model |
| Readiness | `StreamRuntime` |
| Two adapters, one codebase | In-memory for tests, RabbitMQ Streams in Docker |

## Continue In The Part 1 Project

Open the `task-api` directory you completed in Part 1 and add the stream
packages from the same checkout:

```text
uv add --editable "../tori-py/packages/tori-py-persistent-streams-core"
uv add --editable "../tori-py/packages/tori-py-persistent-streams"
uv add --editable "../tori-py/packages/tori-py-persistent-streams-rabbitmq"
```

`tori-py-persistent-streams-core` defines records, streams, and checkpoints.
`tori-py-persistent-streams` integrates them with ToriPy and includes the
in-memory adapter. `tori-py-persistent-streams-rabbitmq` is the RabbitMQ Streams
adapter used in Step 8.

When this tutorial is complete, the project has this shape:

```text
task-api/
  compose.yaml        new
  task_app/
    __init__.py       package marker
    models.py         unchanged
    state.py          unchanged
    activity.py       new
    services.py       replace
    projection.py     new
    http.py           replace
    streams.py        new
    app.py            replace
    test_app.py       replace
    smoke.py          new
```

## Step 1: Define The Record And The Stream

Create `task_app/activity.py`:

```python
--8<-- "examples/tori_py/tutorials/stream_task_activity/task_app/activity.py"
```

`TaskCreatedV1` is the stream contract. Consumers outlive any one version of
the publisher, so the record name carries a version, and
`forbid_unknown_fields=True` makes an unexpected field an error rather than a
silent loss. `TaskCreatedCodec` turns the record into bytes and back; the stream
itself stores opaque bytes.

`StreamDefinition("tutorial-task-activity-v1", partition_count=2)` names the
physical stream and splits it into two partitions. `TaskIdPartitionKey` sends
every record for one task to the same partition. Records are ordered within a
partition, not across partitions.

`task_activity_binding()` connects the alias `task-activity`, which the
application uses, to that definition and its codec:

- `start=Beginning()` makes a consumer group without a checkpoint read from the
  first record.
- `ExternalCheckpointStrategy` stores each consumer group's position in the
  `InMemoryCheckpointStore` passed in. Step 5 explains why the checkpoints live
  in memory.

`TaskActivityPublisher` is a publisher `Protocol`. The integration implements
it; the method must accept an optional `record_id`, which an exact retry would
reuse.

## Step 2: Publish After Saving

Replace `task_app/services.py`:

```python
--8<-- "examples/tori_py/tutorials/stream_task_activity/task_app/services.py"
```

`create()` saves the task first and publishes second. Every publication returns
a `PublishReceipt`. Only `CONFIRMED` means the adapter accepted the record. Other
outcomes, such as `TIMED_OUT` or `INDETERMINATE`, may or may not have stored it,
so the service does not resend automatically; it raises `ActivityNotRecorded`.

Saving and publishing are two separate steps, not one transaction. If the
process stops between them, or the stream does not confirm, the task exists
without its activity record. Step 4 reports this as `503` instead of hiding it.
An application that must never lose the record writes it to an outbox in the
same database transaction as the task and publishes from the outbox; see
[Microservice Operations](../techniques/microservices/operations.md).

## Step 3: Build The Read Model

Create `task_app/projection.py`:

```python
--8<-- "examples/tori_py/tutorials/stream_task_activity/task_app/projection.py"
```

`@stream_handler(stream=TASK_ACTIVITY, consumer_group="task-activity-log-v1")`
subscribes the method to every partition of the stream. The consumer group name
identifies this reader: another group would receive every record again,
independently. Version the group name together with the read model.

`StreamPayload()` binds the decoded `TaskCreatedV1`, and `StreamRecordContext()`
binds a `StreamContext` with the record ID, partition, and offset.

Delivery is at least once. After a failure or restart, a record can arrive
again. `ActivityLog` keys entries by record ID, so applying the same record
twice leaves one entry. Records within a partition are handled one at a time,
and a checkpoint is saved only after `apply()` returns.

## Step 4: Expose The Read Model And Its Health

Replace `task_app/http.py`:

```python
--8<-- "examples/tori_py/tutorials/stream_task_activity/task_app/http.py"
```

`TaskController` awaits the now asynchronous `create()`. `TaskErrorFilter` maps
`ActivityNotRecorded` to `503` with a detail that says the task was saved.

`GET /activity` returns the read model. It is eventually consistent: right after
`POST /tasks` returns, the handler may not have applied the record yet. The route
is `/activity`, not `/tasks/activity`, because `GET /tasks/{task_id}` is
registered first and would match `/tasks/activity` as a task ID.

`GET /streams/health` reports `StreamRuntime`. `ready` is true only while the
runtime is `running` and no partition is blocked; a decode or handler failure
blocks that partition and changes the state to `degraded`. The route returns
`503` when not ready, so it can serve as a readiness probe.

## Step 5: Compose The Application

Create `task_app/streams.py`:

```python
--8<-- "examples/tori_py/tutorials/stream_task_activity/task_app/streams.py"
```

`stream_adapter_module()` chooses the adapter from `TASK_API_STREAMS`: the
in-memory adapter by default, or RabbitMQ Streams with `rabbitmq`. The rest of
the application does not know which one runs.

`streams_module()` registers the binding and the publisher Protocol. The runtime
options declare `owner_id="task-api"` and `single_instance_consumer_groups=True`:
only one process consumes each group. External checkpoint strategies require
that declaration or replica-unique owner IDs.

The checkpoints are kept in memory on purpose. They describe how far
`ActivityLog` has read, and `ActivityLog` is in memory too. When the process
restarts, both disappear together, and the consumer group reads the stream from
the beginning to rebuild the read model. Checkpoints stored in the broker would
survive the restart while the read model did not, and the new process would
resume after records it no longer has.

Replace `task_app/app.py`:

```python
--8<-- "examples/tori_py/tutorials/stream_task_activity/task_app/app.py"
```

`application_module()` builds a new root module for every application. A stream
adapter and its checkpoints belong to one application, and shutdown closes the
adapter permanently, so each application, including each test, gets new ones.
`PIPELINE` names the global pipe and filter so that tests can apply the same
pipeline.

## Step 6: Run With The In-Memory Adapter

Start the server from the `task-api` root:

```text
uv run tori-py run task_app.app:create_application
```

Create two tasks and read the activity and health:

=== "PowerShell"

    ```powershell
    '{"title":"Plan"}' | curl.exe --silent --show-error -X POST "http://127.0.0.1:8000/tasks" -H "content-type: application/json" --data-binary '@-'
    '{"title":"Ship"}' | curl.exe --silent --show-error -X POST "http://127.0.0.1:8000/tasks" -H "content-type: application/json" --data-binary '@-'
    curl.exe --silent --show-error "http://127.0.0.1:8000/activity"
    curl.exe --silent --show-error "http://127.0.0.1:8000/streams/health"
    ```

=== "Bash"

    ```bash
    curl --silent --show-error -X POST "http://127.0.0.1:8000/tasks" \
      -H "content-type: application/json" --data '{"title":"Plan"}'
    curl --silent --show-error -X POST "http://127.0.0.1:8000/tasks" \
      -H "content-type: application/json" --data '{"title":"Ship"}'
    curl --silent --show-error "http://127.0.0.1:8000/activity"
    curl --silent --show-error "http://127.0.0.1:8000/streams/health"
    ```

Each activity entry shows the partition and offset the record was read from.
The in-memory adapter uses sparse offsets, so offsets within a partition can skip
numbers. The health response lists one status per partition of the consumer
group.

Everything is lost when the process stops: the in-memory stream, the
checkpoints, the read model, and the tasks.

## Step 7: Test With The In-Memory Adapter

Replace `task_app/test_app.py`:

```python
--8<-- "examples/tori_py/tutorials/stream_task_activity/task_app/test_app.py"
```

The tests check that:

1. the service validates titles as in Part 1 and publishes one record per
   created task, using a `RecordingPublisher` that stands in for the stream;
2. the Part 1 HTTP contract still holds;
3. created tasks appear in `/activity`, and `/streams/health` reports a ready,
   running runtime;
4. a redelivered record leaves one entry;
5. when the stream does not confirm a record, `POST /tasks` returns `503`, and
   the task is saved anyway.

The activity test waits with a deadline instead of asserting right after the
create, because the read model is eventually consistent. The last test replaces
the publisher Protocol through `TestingModule.override_global()`, which is how a
test reaches outcomes the in-memory adapter never produces.

Run them:

```text
uv run pytest task_app/test_app.py -q
```

Expected result: `5 passed`.

## Step 8: Run On RabbitMQ Streams

Create `compose.yaml` in the `task-api` root:

```yaml
--8<-- "examples/tori_py/tutorials/stream_task_activity/compose.yaml"
```

It runs RabbitMQ 4.1 with the stream plugins. `advertised_host localhost` makes
the broker tell clients to connect to `localhost:5552`, which the port mapping
publishes. The user and password are local demonstration values.

Start the broker and wait until it is healthy:

```text
docker compose up -d --wait
```

Run the application against it:

=== "PowerShell"

    ```powershell
    $env:TASK_API_STREAMS = "rabbitmq"
    uv run tori-py run task_app.app:create_application
    ```

=== "Bash"

    ```bash
    TASK_API_STREAMS=rabbitmq uv run tori-py run task_app.app:create_application
    ```

The adapter creates the Super Stream `tutorial-task-activity-v1` with partitions
`tutorial-task-activity-v1-0` and `-1` on first start; open
`http://localhost:15672` (user `tutorial`) to see them under **Queues and
Streams**. Create
tasks as in Step 6, then stop and start the server. `/activity` shows the same
entries again: the stream is in RabbitMQ, and the new process rebuilt its read
model from the beginning. `/tasks` is empty, because the task repository is
still in memory. For the same reason new tasks start again from id 1, so
`/activity` can list two entries with the same `task_id`. Both stay, because
the read model keys entries by record ID.

`task_app/smoke.py` automates that check:

```python
--8<-- "examples/tori_py/tutorials/stream_task_activity/task_app/smoke.py"
```

```text
uv run python -m task_app.smoke
```

Stop the broker and delete its data when you are done:

```text
docker compose down -v
```

[RabbitMQ Streams Adapter](../techniques/persistent-streams/rabbitmq.md) covers
TLS, credentials, retention, and the adapter's provisional status before any
production use.

## Guarantees And Limits

- **At least once.** A record can be handled more than once; the read model
  must tolerate it. It is never handled by two members of one consumer group at
  the same time in this single-process setup.
- **Not atomic with the save.** A task can exist without its activity record.
  Use an outbox when that is not acceptable.
- **Order is per partition.** Two tasks can be handled in a different order than
  they were created; records for one task keep their order.
- **Rebuilding depends on retention.** The read model is rebuilt from the
  beginning of the stream. RabbitMQ deletes old segments after the retention
  limits, by default 7 days or 1 GiB, and records deleted that way cannot be
  rebuilt; see
  [Checkpoints and Retention](../techniques/persistent-streams/checkpoints-and-retention.md).
- **One consumer process.** `single_instance_consumer_groups=True` is a
  declaration, not a lock. Running two copies against the same broker breaks
  it.
- **Demonstration credentials.** The compose file and defaults are for a local
  broker only.

## Next Steps

- [Core Concepts](../techniques/persistent-streams/core.md): records, routing,
  starts, and leases.
- [Handlers and Publishers](../techniques/persistent-streams/handlers-and-publishers.md):
  every binding, runtime option, and publisher surface.
- [Checkpoints and Retention](../techniques/persistent-streams/checkpoints-and-retention.md):
  checkpoint strategies, gaps, and poison records.
- [Persistent Stream Operations](../techniques/persistent-streams/operations.md):
  readiness, status, and recovery.
- [Part 4: Add Event Sourcing](event-sourced-application.md): streams between
  several processes.
