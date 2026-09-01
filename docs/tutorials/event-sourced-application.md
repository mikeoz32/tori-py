# Part 4: Event-Source the Task API

This continuation of [Part 3](distributed-application.md) makes the Task API
series' first semantic consistency change. The `Task` JSON shape and all
existing paths remain unchanged, and `PATCH /tasks/{task_id}` is added. However,
`GET /tasks` and `GET /tasks/{task_id}` now read an eventually updated
projection instead of command-owned state. A `404` therefore means that the task
is absent from the **current projection view**. It does not prove that no command
for that task committed.

The public contract is now:

| Request | Success | Consistency boundary |
| --- | --- | --- |
| `POST /tasks` with `{"title":"..."}` | `201` with the created `Task` | Confirms the observed event-store command outcome, not projection convergence |
| `PATCH /tasks/{task_id}` with `{"title":"..."}` | `200` with the renamed `Task` | Confirms the observed event-store command outcome, not projection convergence |
| `GET /tasks` | `200` with `list[Task]` | Reads the projection as it exists when the query runs |
| `GET /tasks/{task_id}` | `200` with one `Task`, or `404` | Reads only the current projection view |

`Task` is still exactly `{"id": int, "title": str}`. Title normalization,
strict request validation, and Problem Details remain at the same HTTP boundary.
A successful command can be followed briefly by an empty list, a stale title, or
a `404` until the relay and projection consumer catch up.

Every non-marker file below is complete. The snippets are the canonical,
executable snapshot under
`examples/tori_py/tutorials/event_sourced_task_api`.

## What You Will Build

Part 4 replaces the Part 3 package with four independent Tori Py application
roots:

| Root | Owns | Does not own |
| --- | --- | --- |
| `gateway` | HTTP, validation, two typed RPC clients, HTTP error mapping | Task decisions, event storage, projection state, stream consumption |
| `tasks` | Create and rename commands, local CQRS command dispatch, the task aggregate, event store, ID allocation, and event relay | HTTP, query RPC, projection and audit effects |
| `projection` | Persistent-stream projection consumer, task read state, list/get RPC | Task commands, aggregate writes, HTTP |
| `audit` | An independent persistent-stream consumer group and idempotent audit effect | Task commands, task reads, HTTP, RPC |

The complete flow is:

```text
HTTP client
    |
    v
gateway
    |-- AMQP 0-9-1 RPC --> task command service
    |                         |
    |                         v
    |                    local CommandBus
    |                         |
    |                         v
    |                    aggregate + EventStore
    |                         |
    |                         | after_commit wakes relay
    |                         v
    |                    committed read_all pages
    |                         |
    |                         | native RabbitMQ Streams
    |                         v
    |                  tutorial-task-events-v1
    |                    /                 \
    |                   v                   v
    |           projection group       audit group
    |                   |
    |-- AMQP 0-9-1 RPC -+
```

The same RabbitMQ node can host both network paths, but they are not the same
transport:

| Boundary | Protocol and port | Purpose |
| --- | --- | --- |
| Gateway to command/projection services | AMQP 0-9-1 on `5672` | Finite-deadline typed request/reply RPC |
| Relay and projection/audit consumers | Native RabbitMQ Streams on `5552` | Retained, partitioned, independently checkpointed records |
| Task command transaction | `EventStore` API inside the task root | Aggregate history, optimistic versions, and a committed global read sequence |

The event store is not RabbitMQ. Native Persistent Streams are not the
microservices event dispatcher used in Part 3. AMQP RPC does not carry local CQRS
objects.

## Keep The Four Message Kinds Separate

Several values describe the same business change at different boundaries. Do
not treat them as interchangeable:

| Kind | Examples | Owner and lifetime |
| --- | --- | --- |
| Local CQRS messages | `CreateTask`, `RenameTask` | In-process command routing inside the task root only |
| Domain events | `TaskCreated`, `TaskRenamed` | Aggregate facts raised and replayed by the event-sourcing model |
| Stored event records | `StoredEvent` containing an encoded event and metadata | Immutable event-store representation with stream and global positions |
| Persistent-stream DTO | `TaskEventRecordV1` | Versioned integration payload created by the application relay |
| Persistent-stream envelope | Canonical PSRM v2 bytes around the DTO | Adapter transport record containing record ID, partition key, headers, and payload |
| RPC DTOs | `CreateTaskV1`, `RenameTaskV1`, `GetTaskV1`, `ListTasksV1`, `Task` | Versioned request/reply contracts shared by RPC clients and servers |

The relay decodes a stored domain event and deliberately translates it into a
stream DTO. The RabbitMQ Streams adapter then wraps the encoded DTO in its
canonical envelope. Neither translation turns a domain event into a CQRS
message, an RPC request, or the original stored record.

## Continue In The Same Project

Use the same `task-api` consumer project from Part 3. Keep Python
`>=3.14,<3.15`, the existing `task-api` project name, and all existing Part 3
dependencies. Do not initialize a new project.

The event-sourcing and persistent-stream packages are not published yet. With
the Tori Py checkout still in the sibling `../tori-py` directory, add the exact
source-checkout dependency delta:

```text
uv add --editable "../tori-py/packages/tori-py-cqrs-event-sourcing-core"
uv add --editable "../tori-py/packages/tori-py-cqrs-event-sourcing"
uv add --editable "../tori-py/packages/tori-py-persistent-streams-core"
uv add --editable "../tori-py/packages/tori-py-persistent-streams"
uv add --editable "../tori-py/packages/tori-py-persistent-streams-rabbitmq"
```

Keep this project metadata constraint:

```toml
[project]
name = "task-api"
requires-python = ">=3.14,<3.15"
```

The RabbitMQ adapter adds its pinned native Streams driver. Part 3's editable
`tori-py-microservices[rabbitmq]` dependency remains responsible for AMQP RPC.
Use `uv` for every install, test, and process command so all distributions resolve
in the same environment.

## Replace The Complete Package Tree

Delete the Part 3 `task_app/` package and replace it completely. Place
`compose.yaml` at the consumer project root, next to `pyproject.toml`:

```text
task-api/
  .python-version
  compose.yaml
  pyproject.toml
  uv.lock
  task_app/
    __init__.py
    contracts.py
    infrastructure.py
    streams.py
    testing.py
    test_domain.py
    test_gateway_errors.py
    test_system.py
    audit/
      __init__.py
      app.py
    gateway/
      __init__.py
      app.py
    projection/
      __init__.py
      app.py
      state.py
    tasks/
      __init__.py
      app.py
      domain.py
      handlers.py
      messages.py
      relay.py
      repository.py
      schemas.py
      services.py
      state.py
```

The five `__init__.py` files are package markers. They may be empty or contain
only a module docstring; they define no providers or runtime behavior. Every
behavioral file follows.

## Step 1: Split Command And Read Contracts

Create `task_app/contracts.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/contracts.py"
```

Part 3 exposed commands and reads under `tutorial.tasks.v1`. Part 4 deliberately
replaces that identity with two owners:

- `tutorial.task-commands.v1` accepts `create-task` and `rename-task`;
- `tutorial.task-projection.v1` serves `list-tasks` and `get-task`.

This is a coordinated RPC identity cutover, not a backward-compatible rolling
upgrade. Deploy the gateway and both matching server identities together. If old
callers must remain live, build and operate an explicit compatibility service;
this tutorial does not hide one in either root.

All four RPC methods retain positive, finite two-second deadlines. A command RPC
timeout stops the gateway's wait but does not cancel a handler that already
started or prove that its event-store transaction did not commit.

## Step 2: Define The Persistent Stream

Create `task_app/streams.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/streams.py"
```

The binding fixes one application alias, one physical stream contract, one DTO
and codec, and one partitioning rule:

```text
application alias: task-events
physical stream:   tutorial-task-events-v1
partitions:         2
payload:            TaskEventRecordV1 JSON
partition key:      ASCII task ID
new-group start:    Beginning
```

All records for one task resolve from the same stable task-ID key and therefore
stay on one partition. Different task IDs can use different partitions. Order is
meaningful within a partition; no consumer should infer one cross-partition
delivery order.

`TaskEventRecordV1` is the explicit integration schema. Its fields retain the
source domain event ID, aggregate version, event-store global position, and
occurrence time, but the DTO is not a `StoredEvent`. The RabbitMQ adapter encodes
the DTO again inside canonical PSRM v2, whose binary envelope carries the record
UUID, partition key, headers, and payload. Application headers remain in that
envelope rather than becoming arbitrary flat AMQP headers.

The four positions and identities have different jobs:

| Value | Scope | Use |
| --- | --- | --- |
| `event_id` | One immutable fact | Deduplicate the same fact across relay publication and consumer redelivery |
| `stream_version` / `aggregate_version` | One aggregate stream such as `task-1` | Enforce create at version 1 and gap-free renames for that task |
| `global_position` / `source_global_position` | One event store | Let the relay scan committed records in source order and retain source provenance |
| Persistent-stream partition offset | One physical partition | Let each consumer group resume delivery through its checkpoint |

A global position is not a partition offset. Aggregate version 2 can have any
store-global position and any broker partition offset. The stable UUID is copied
into the stream DTO and passed as the persistent-stream `record_id`; positions
must never be substituted for that identity.

When an `InMemoryCheckpointStore` is supplied, `task_event_binding()` selects an
external checkpoint strategy with a stable identity. Without one, it selects the
adapter's broker-managed strategy. The projection and audit roots below each
supply their own external in-memory store.

## Step 3: Add Process And Broker Infrastructure

Create `task_app/infrastructure.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/infrastructure.py"
```

AMQP RPC and native Streams use separate connection settings. The tutorial
defaults are `localhost:5672` for AMQP and `localhost:5552` for Streams with the
educational `tutorial` credentials. `serve()` owns lifecycle for the three
non-HTTP processes. The gateway instead lets ASGI lifespan start and stop its
application.

Create the root-level `compose.yaml`:

```yaml
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/compose.yaml"
```

The broker enables both `rabbitmq_stream` and `rabbitmq_stream_management`, then
publishes AMQP, native Streams, and the management UI. These credentials and
plain local ports are for this tutorial only.

## Step 4: Model The Aggregate And Stored Schemas

Create `task_app/tasks/domain.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/tasks/domain.py"
```

`TaskAggregate` starts at version 0 with no title. `create()` can run only once;
it normalizes the title, raises `TaskCreated`, and immediately applies that event
to aggregate state. `rename()` requires a created aggregate and raises
`TaskRenamed` only when the normalized title actually changes. Renaming to the
current normalized title is a no-op with no pending event.

`_apply()` is the single state transition path for both newly raised events and
historical replay. Loading an aggregate replays versioned events through this
method. After a confirmed commit, the integration advances the aggregate's
committed version and clears its pending events before returning the command
result. The first create is version 1; its first effective rename is version 2.

Create `task_app/tasks/schemas.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/tasks/schemas.py"
```

Persisted type identity is explicit and stable:

```text
tasks.task-created, schema version 1
tasks.task-renamed, schema version 1
```

Python class names are not storage aliases. The codecs require exactly
`task_id` and `title`, reject booleans as IDs, validate normalized UTF-8 titles,
and write deterministic compact JSON. The frozen registry prevents runtime
schema mutation. Evolving stored data requires a new schema version and an
explicit decoder/upcaster policy, not silently changing version 1.

## Step 5: Declare Commands, Repository, And IDs

Create `task_app/tasks/messages.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/tasks/messages.py"
```

These are local CQRS commands. The RPC controller translates `CreateTaskV1` and
`RenameTaskV1` wire DTOs into them. They never cross RabbitMQ and are not domain
events.

Create `task_app/tasks/repository.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/tasks/repository.py"
```

`@aggregate_repository` declares how `TaskAggregate` maps to category `task` and
encodes integer IDs into stream IDs. The generated feature provider is
request-scoped. Here, request scope means one local CQRS command invocation, not
one gateway HTTP request or one AMQP delivery object.

Create `task_app/tasks/state.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/tasks/state.py"
```

`TaskIdSequence` is intentionally outside the aggregate. Validation occurs
before `next()`, so a rejected title does not consume an ID. It is still only a
singleton counter in one task process:

- restart resets it to 1;
- replicas allocate conflicting IDs independently;
- an unknown command outcome makes client retry unsafe;
- allocation is not transactionally coordinated with the event store;
- resetting it while old stream records remain can reuse semantic identities.

It is an educational allocator, not a production identity boundary.

## Step 6: Relay Committed Records

Create `task_app/tasks/relay.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/tasks/relay.py"
```

`TaskEventRelay` is application code. Tori Py does not automatically bridge an
event store to Persistent Streams, and this snapshot does not add a separate
outbox. The relay uses the event store's committed global log as its source:

1. Start at the process-local global checkpoint, initially 0.
2. Read committed `read_all()` pages after that position, bounded to 100 records.
3. Decode each stored event through the stable event-store schema registry.
4. Translate it to `TaskEventRecordV1`.
5. Publish with the event UUID as `record_id`.
6. Advance the relay checkpoint only for `CONFIRMED` or `DEDUPLICATED` receipts.

The command synchronization callback registered with `after_commit` only sets a
wake event. It does not publish, carry the committed event as an in-memory
message, wait for a consumer, or make the command and broker publication one
transaction. On startup, the relay also wakes itself so it can scan committed
history even when no new callback occurs.

Backpressure is retried at most three times because it is a proven local no-send
outcome. A timed-out, indeterminate, rejected, closed, or otherwise unsafe
publication fails closed: the relay records its failure, does not automatically
resend, and stops advancing. A confirm can be followed by a crash before relay
checkpoint advancement, so replay can still publish the same event again.
Consumers must remain duplicate-safe.

Once degradation is visible, `require_available()` rejects new create and rename
commands before ID allocation or repository access. A command already in flight
can race the degradation transition. There is no automatic restart, outbox,
exactly-once bridge, or reconciliation worker.

Shutdown also has a deliberate caveat. The relay's lifecycle hook cancels its
task, but this snapshot does not prove cross-provider ordering that publishes
every committed event before the Persistent Streams runtime closes. Stop command
admission first, observe convergence, and only then stop the task process.

## Step 7: Run Each Command In A Unit Of Work

Create `task_app/tasks/handlers.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/tasks/handlers.py"
```

Decorator order matters: `@command_handler` is applied first, so
`@use_event_sourcing` appears above it in source. Both handlers use
`Scope.REQUEST` because they inject a request-scoped aggregate repository.

For each local command, `@use_event_sourcing(key="tasks")` provides this
lifecycle:

```text
CommandBus selects the handler
-> open a fresh handler-owner work scope
-> enter one event-sourcing unit of work
-> resolve the request-scoped repository and handler
-> load/create, decide, and stage pending aggregate events
-> commit on normal return or roll back on failure
-> run the matching command-synchronization callbacks
-> finalize the scope
-> return the result or a typed finalization outcome
```

The handler does not inject a unit of work or call `commit()`. Repository access
is leased to the exact command-handler task and transaction boundary; it cannot
escape into child tasks, callbacks, query handlers, or later use.

Create validates before allocating an ID, creates the aggregate, saves it, and
registers the relay wake for a confirmed commit. Rename replays the aggregate
from its event stream, applies the decision, and saves/registers a wake only when
an effective rename produced a pending event. A no-op rename still completes its
managed command lifecycle but appends no stored event.

Create `task_app/tasks/services.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/tasks/services.py"
```

The service is the narrow RPC-to-CQRS facade. There are no local query messages
in this root because reads belong to the projection service.

## Step 8: Compose The Command Root

Create `task_app/tasks/app.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/tasks/app.py"
```

The root composes five explicit boundaries:

- `TaskPersistenceModule` owns one `InMemoryEventStore`;
- the keyed event-sourcing root owns schemas, transaction coordination, and
  synchronization;
- the feature module supplies the request-scoped `TaskRepository`;
- local CQRS discovers the two command handlers;
- microservices serves the command RPC identity over AMQP while Persistent
  Streams supplies the relay publisher over the native Streams adapter.

The RPC controller converts expected outcomes to stable public codes. It does
not serialize internal exceptions. Optimistic concurrency becomes `conflict`;
missing rename aggregates become `not_found`; relay degradation becomes
`relay_unavailable`; and commit/finalization uncertainty remains explicit rather
than being reported as a normal failure.

The command response is released only after the event-sourcing interceptor has
classified commit and finalization. It does **not** wait for relay publication,
projection handling, audit handling, or either consumer checkpoint.

## Step 9: Build The Projection Root

Create `task_app/projection/state.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/projection/state.py"
```

The projection tracks tasks, the last aggregate version per task, and the full
DTO previously associated with each event UUID. Its rules are fail-stop:

- an exact duplicate event UUID and equal DTO counts as another delivery but
  makes no state change;
- reusing an event UUID with different contents marks the whole projection
  unavailable;
- `task-created` must be aggregate version 1 and must not replace an existing
  task;
- `task-renamed` must be exactly the current aggregate version plus one;
- a missing version or gap marks the projection unavailable rather than guessing
  or skipping.

These are aggregate-version rules, not global-position rules. Records for other
tasks can occupy positions between two events for task 1 without creating an
aggregate gap.

Create `task_app/projection/app.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/projection/app.py"
```

The projection has two controllers in one root. The stream controller consumes
group `task-projection-v1`; the RPC controller serves projection-only list/get
reads under `tutorial.task-projection.v1`. A miss maps to `not_found`. A violated
projection invariant maps all later reads to retryable
`projection_unavailable` rather than serving known-corrupt state.

`PROJECTION_CHECKPOINTS` is an external checkpoint store only in the protocol
sense: it is an `InMemoryCheckpointStore` held by this process. Each of the two
physical partitions has independent group progress. `Beginning()` applies only
when no checkpoint exists. The stable group and checkpoint identities are data
contracts, while `single_instance_consumer_groups=True` is only a deployment
declaration; it does not create a distributed lock or make replicas safe.

For each delivered record, the integration orders work as:

```text
decode TaskEventRecordV1
-> open work scope and run pipeline
-> TaskProjectionState.apply()
-> unwind interceptors
-> finalize work scope
-> persist and verify the partition checkpoint
```

The checkpoint advances only after the handler and scope cleanup succeed. It is
not atomic with the in-memory projection effect. A crash after the effect and
before checkpoint completion can deliver the record again, which is why exact
duplicates are no-ops.

## Step 10: Build The Audit Root

Create `task_app/audit/app.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/audit/app.py"
```

Audit consumes the same stream through independent group `task-audit-v1` and an
independent external in-memory checkpoint identity. Projection progress cannot
advance audit progress, and an audit failure cannot be hidden by a successful
projection checkpoint.

`TaskAuditLog` counts every delivery but stores one entry per event UUID. An
exact duplicate is idempotent. Reusing a UUID with different contents raises
`AuditEventConflict`; the handler fails, so that record is not safely
checkpointed and the affected stream partition degrades. This in-memory map is
the shape of an idempotent consumer, not a durable inbox or audit system.

The same handler-before-checkpoint ordering applies. In production, the inbox
identity, durable audit effect, and consumer progress need one local transaction
or a recovery design that explicitly closes their failure windows.

## Step 11: Route HTTP By Responsibility

Create `task_app/gateway/app.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/gateway/app.py"
```

The gateway injects both typed Protocols:

```text
POST  /tasks           -> TaskCommandService.create_task()
PATCH /tasks/{task_id} -> TaskCommandService.rename_task()
GET   /tasks           -> TaskProjectionService.list_tasks()
GET   /tasks/{task_id} -> TaskProjectionService.get_task()
```

It is client-only and claims no service identity. `ClientsModule` serves both
contracts through one AMQP client transport while preserving their distinct
logical destinations and finite deadlines.

The error filter applies this exact boundary mapping:

| Upstream outcome | HTTP | Gateway meaning |
| --- | ---: | --- |
| HTTP validation or binding exception | Exception's status, normally `400` | The local HTTP request was invalid |
| `invalid_request` | `400` | The command rejected the normalized title |
| `not_found` | `404` | Rename aggregate missing, or task absent from the current projection |
| `conflict` | `409` | Optimistic command conflict |
| `projection_unavailable`, `relay_unavailable` | `503` | The owning service is degraded |
| `command_committed_finalization_failed` | `502` | Commit is confirmed but command finalization failed |
| `command_finalization_failed` | `502` | Non-commit is confirmed but finalization failed |
| `command_outcome_unknown` or unknown remote code | `502` | The exchange cannot establish a normal command result |
| Unknown service | `503` | The command or projection identity is unavailable |
| RPC timeout | `504` | The finite local wait expired |
| RPC outcome unknown or indeterminate transport | `502` | Acceptance/completion cannot be established |
| Transport operation timeout | `504` | A transport operation exceeded its deadline |
| Protocol error or other RPC client error | `502` | No valid service response was produced |
| RabbitMQ connection or transport unavailable | `503` | The dependency transport is unavailable |
| Unexpected exception | `500` | Sanitized gateway failure |

For command RPC, `502` and `504` do not mean "safe to retry." The command may
have committed before its reply or finalization outcome was lost. This API still
has no business idempotency key or persisted command result, so blindly retrying
`POST` can allocate a second task and blindly retrying `PATCH` can race another
write. Reconcile through an application-owned identity before retrying an
unknown command outcome. Publisher confirmation later in the relay likewise
means broker acceptance, not projection or audit completion.

## Step 12: Add Deterministic Test Adapters

Create `task_app/testing.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/testing.py"
```

Tests use one `InMemoryBroker` for typed RPC and one
`InMemoryPersistentLog` shared through application-owned handles. Closing an
individual audit, projection, or task handle does not close the central log while
another root still uses it; the test context closes that log exactly once after
all four applications stop.

The replacements preserve all four production composition roots. They replace
only each production RabbitMQ adapter descriptor with a keyed in-memory module;
controllers, contracts, codecs, handlers, repositories, modules, CQRS,
event-sourcing integration, pipelines, and lifecycle remain the production
definitions. `RelayGate` is the one explicit provider override used to pause
publication deterministically.

## Step 13: Test Domain And Failure Rules

Create `task_app/test_domain.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/test_domain.py"
```

These tests pin title invariants, exact stored JSON, stable aliases and schema
versions, replayed aggregate versions, no-op rename behavior, projection gaps,
audit conflicts, indeterminate relay fail-stop behavior, and command rejection
after degradation.

Create `task_app/test_gateway_errors.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/test_gateway_errors.py"
```

These focused assertions keep command finalization and relay failures behind
stable RPC codes, then verify standard Problem Details titles and the command
timeout warning.

Create `task_app/test_system.py`:

```python
--8<-- "examples/tori_py/tutorials/event_sourced_task_api/task_app/test_system.py"
```

The system test starts the unchanged production roots in dependency order:
audit, projection, tasks, then gateway. The closed relay gate makes three
successful creates remain absent from the projection, proving both stale list
and current-view `404` behavior without sleeps. Releasing it proves bounded
convergence; pausing it around rename proves that a command response can contain
the new title while `GET` still returns the old title.

The test then verifies:

- created records occupy both physical partitions;
- the event store retains stable aliases, schema versions, aggregate versions,
  and source ordering;
- stream DTOs retain event IDs, aggregate versions, and source global positions;
- projection and audit use separate consumer groups;
- republishing an exact record creates another delivery but no duplicate effect;
- a conflicting projection duplicate fails closed;
- all applications, RPC transports, stream runtimes, shared handles, broker, and
  central log complete lifecycle shutdown.

Run all three files from the consumer project root:

```text
uv run pytest task_app -q
```

Expected result:

```text
............................                                             [100%]
28 passed
```

!!! warning "This is not RabbitMQ or process proof"

    The test opens no RabbitMQ connection and runs all four roots in one Python
    process. It does not prove native Streams topology, publisher confirms,
    broker checkpoints, retention, redelivery after disconnect, process
    isolation, restart safety, replica fencing, reconnect, failover, or
    exactly-once effects. Keep real-broker and multi-process acceptance tests as
    a separate layer.

## Run The Production Roots With RabbitMQ

"Production roots" here means the unmodified RabbitMQ compositions from the
example, not a claim that their in-memory state is production-ready.

Make sure the `compose.yaml` shown above is at the consumer project root. Start
RabbitMQ and wait for its container healthcheck:

```text
docker compose up --wait
```

Verify the node, required plugins, and published ports:

```text
docker compose exec rabbitmq rabbitmq-diagnostics -q ping
docker compose exec rabbitmq rabbitmq-plugins is_enabled rabbitmq_stream rabbitmq_stream_management
docker compose port rabbitmq 5672
docker compose port rabbitmq 5552
docker compose port rabbitmq 15672
```

The expected host ports are AMQP `5672`, native Streams `5552`, and management
HTTP `15672`. The management UI is `http://127.0.0.1:15672` with
`tutorial` / `tutorial`. Container health proves that the node responds; the
plugin and port checks still do not prove application readiness.

### Start The Four Processes

Open four terminals at the consumer project root. Start the consumers first so
their topology and intake are ready before commands can publish, and expose HTTP
last. Wait for each process to complete application startup before starting the
next one.

#### 1. Audit

=== "PowerShell"

    ```powershell
    uv run python -m task_app.audit.app
    ```

=== "Bash"

    ```bash
    uv run python -m task_app.audit.app
    ```

#### 2. Projection

=== "PowerShell"

    ```powershell
    uv run python -m task_app.projection.app
    ```

=== "Bash"

    ```bash
    uv run python -m task_app.projection.app
    ```

#### 3. Task Commands And Relay

=== "PowerShell"

    ```powershell
    uv run python -m task_app.tasks.app
    ```

=== "Bash"

    ```bash
    uv run python -m task_app.tasks.app
    ```

#### 4. HTTP Gateway

=== "PowerShell"

    ```powershell
    uv run uvicorn task_app.gateway.app:application --lifespan on --host 127.0.0.1 --port 8000
    ```

=== "Bash"

    ```bash
    uv run uvicorn task_app.gateway.app:application \
      --lifespan on --host 127.0.0.1 --port 8000
    ```

Each startup barrier covers only resources owned by that process. This snapshot
has no cross-process readiness coordinator or service health endpoint.

### Create, Read, And Rename

Create task 1:

=== "PowerShell"

    ```powershell
    '{"title":"  Ship the event-sourced tutorial  "}' |
      curl.exe --silent --request POST "http://127.0.0.1:8000/tasks" `
        --header "content-type: application/json" `
        --data-binary '@-' `
        --write-out "`nHTTP %{http_code}`n"
    ```

=== "Bash"

    ```bash
    curl --silent --request POST "http://127.0.0.1:8000/tasks" \
      --header "content-type: application/json" \
      --data '{"title":"  Ship the event-sourced tutorial  "}' \
      --write-out '\nHTTP %{http_code}\n'
    ```

The command response is:

```text
{"id":1,"title":"Ship the event-sourced tutorial"}
HTTP 201
```

Read the current projection:

=== "PowerShell"

    ```powershell
    curl.exe --silent "http://127.0.0.1:8000/tasks" --write-out "`nHTTP %{http_code}`n"
    curl.exe --silent "http://127.0.0.1:8000/tasks/1" --write-out "`nHTTP %{http_code}`n"
    ```

=== "Bash"

    ```bash
    curl --silent "http://127.0.0.1:8000/tasks" --write-out '\nHTTP %{http_code}\n'
    curl --silent "http://127.0.0.1:8000/tasks/1" --write-out '\nHTTP %{http_code}\n'
    ```

Normally the local projection converges quickly and returns the created task.
An immediate read is still allowed to return `[]` or `404`; repeat the safe GET
after the projection advances. This is observation of eventual consistency, not
a monotonic-read guarantee.

Rename the task:

=== "PowerShell"

    ```powershell
    '{"title":"  Publish through the relay  "}' |
      curl.exe --silent --request PATCH "http://127.0.0.1:8000/tasks/1" `
        --header "content-type: application/json" `
        --data-binary '@-' `
        --write-out "`nHTTP %{http_code}`n"
    curl.exe --silent "http://127.0.0.1:8000/tasks/1" --write-out "`nHTTP %{http_code}`n"
    ```

=== "Bash"

    ```bash
    curl --silent --request PATCH "http://127.0.0.1:8000/tasks/1" \
      --header "content-type: application/json" \
      --data '{"title":"  Publish through the relay  "}' \
      --write-out '\nHTTP %{http_code}\n'
    curl --silent "http://127.0.0.1:8000/tasks/1" \
      --write-out '\nHTTP %{http_code}\n'
    ```

The `PATCH` response can show `Publish through the relay` while the following
`GET` still shows the previous title. Once the projection consumes aggregate
version 2 and checkpoints it, the read returns the renamed `Task`.

### Shut Down In Reverse Order

Stop admission and producers before consumers:

1. Press `Ctrl+C` in the gateway terminal and wait for ASGI lifespan shutdown.
2. Confirm that the observed projection/audit have caught up with accepted
   command traffic, then press `Ctrl+C` in the task terminal.
3. Press `Ctrl+C` in the projection terminal.
4. Press `Ctrl+C` in the audit terminal.
5. Remove the broker and its retained data:

```text
docker compose down -v
```

The order matters because forced or early task shutdown can leave a committed
event behind the in-memory relay checkpoint and unpublished to the stream. The
example has no operational drain endpoint, so convergence is an observation and
procedure rather than a guaranteed shutdown barrier.

To reset the tutorial, stop all four Python processes, remove broker data, start
a fresh broker, and restart the applications in audit/projection/tasks/gateway
order:

```text
docker compose down -v
docker compose up --wait
```

Do not reset only the task process while retaining
`tutorial-task-events-v1`. Its empty event store and reset ID allocator can emit
new task IDs and aggregate versions that conflict semantically with retained
records. A coherent reset includes the command event store, ID allocator, relay
checkpoint, physical stream, both consumer checkpoints, projection, and audit.

## Understand The Deliberate Limitations

This application demonstrates boundaries and failure policy, not production
durability:

- `InMemoryEventStore` loses aggregate history, event IDs, versions, and global
  relay source data when the task process stops.
- `TaskIdSequence` resets and cannot coordinate process replicas or unknown
  command retries.
- the relay checkpoint is one integer in task-process memory and has no durable
  ownership, fencing, or restart reconciliation.
- projection rows, projection event IDs/versions, audit entries, and both
  `InMemoryCheckpointStore` instances are process-local memory.
- retaining the RabbitMQ stream while restarting an empty writer is incompatible
  with safe identity/version evolution; reset all state together or migrate to
  durable coordinated stores.
- the RabbitMQ Persistent Streams adapter is a provisional conditional beta, not
  an unconditional production-readiness claim.
- this tutorial supplies no production-qualified durable event-store adapter, ID
  allocator, relay checkpoint, projection store, audit inbox, or external
  checkpoint adapter.
- there is no transactional outbox, automatic event-store bridge, distributed
  transaction, or exactly-once publication/processing guarantee.
- reads are eventual and provide no read-your-writes or monotonic-read guarantee.
- `single_instance_consumer_groups=True` is a declaration, so command,
  projection, audit, and checkpoint state are not safe for replicas.
- there is no retention-gap repair, snapshot restore, governed skip, or automatic
  rebuild/cutover procedure.
- the provisional adapter fails closed on connection loss; this snapshot proves
  no reconnect, replica transfer, cluster failover, or disaster recovery.
- a publisher confirm proves broker acceptance only. It does not prove consumer
  execution, handler success, checkpoint completion, exactly-once effect, append
  offset, or per-message disk synchronization.

At-least-once windows remain on both sides. The relay can republish after a
confirm/checkpoint crash window, and a consumer can repeat an effect after an
effect/checkpoint crash window. Stable event IDs and aggregate versions let this
example detect duplicates and gaps, but in-memory detection disappears on
restart.

## Production Next Steps

1. Replace the command state with a durable event store, durable conflict-safe ID
   allocator, and durable fenced relay checkpoint that can reconcile uncertain
   publication outcomes.
2. Store each projection or audit effect with a durable inbox identity and its
   consumer checkpoint in one local transaction, including a clear poison-record
   policy.
3. Rebuild into a new governed consumer group and versioned projection, validate
   it against retained source history, then perform an explicit read-identity
   cutover with rollback criteria.
4. Operate reconciliation for event-store versus stream progress, consumer lag,
   duplicate/conflict evidence, retention low watermarks, blocked partitions,
   and indeterminate command or publication outcomes.
