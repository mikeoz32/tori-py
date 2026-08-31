# Part 3: Distribute the Task API

Part 2 put commands, queries, and events behind one Task API. In this part, you
keep the HTTP contract and split its implementation into three independently
composed ToriPy applications:

- `gateway` owns HTTP and calls the task service through typed RPC;
- `tasks` owns task state, local CQRS, the task RPC contract, and integration
  event publication;
- `audit` consumes the integration event and records an idempotent local effect.

RabbitMQ connects those application roots. CQRS remains local to the task
service. The split is an implementation and deployment change, not permission
to send local `Command`, `Query`, or `Event` objects over the network.

Every Python file shown here is complete. The snippets come from the executable
copy under `examples/tori_py/tutorials/distributed_task_api/task_app`, and the
repository runs its system test to keep the tutorial aligned with the public
APIs.

## What You Will Build

The public gateway preserves the Task API:

| Request | Success | Remote work |
| --- | --- | --- |
| `POST /tasks` with `{"title":"..."}` | `201` with the created `Task` | Execute a local command, write the task, and publish a routed integration event |
| `GET /tasks` | `200` with `list[Task]` | Execute a local list query in the task service |
| `GET /tasks/{task_id}` | `200` with one `Task` | Execute a local get query in the task service |

The gateway also preserves application error semantics: an invalid normalized
title is `400`, and a missing task is `404`. Clients do not need RabbitMQ
routing keys, RPC envelopes, CQRS types, or knowledge of the audit service.

The runtime flow is:

```text
HTTP client
    |
    v
gateway: HTTP controller + typed TaskService proxy
    |
    | RabbitMQ RPC, tutorial.tasks.v1, finite 2 second deadline
    v
task service: RPC controller -> TaskApplicationService
    |                              |
    | local CommandBus/QueryBus    | awaited EventDispatcher.publish()
    v                              v
TaskRepository + local metrics    task-created.v1 integration event
                                       |
                                       | RabbitMQ SERVICE_POOL subscription
                                       v
                                  audit service -> AuditLog
```

The three roots have explicit ownership:

| Root | Owns | Does not own |
| --- | --- | --- |
| Gateway | HTTP routes, validation, typed RPC client, HTTP error mapping | Task storage, CQRS handlers, audit state, a service runtime |
| Task service | In-memory task state, local CQRS messages and handlers, task RPC methods, integration publication | HTTP, audit entries |
| Audit service | `task-created.v1` subscription and idempotent audit state | Task writes, task queries, HTTP |

There is no shared application container. In production these roots run in
different processes and have separate lifecycle, memory, and broker connections.

## Prepare the Project

Use Python `>=3.14,<3.15`, `uv`, and Docker. Run the commands from the same
consumer project created in Part 2, with the ToriPy checkout still in the sibling
`../tori-py` directory.

The dependency delta from Part 2 is one local editable distribution with its
RabbitMQ extra:

```text
uv add --editable "../tori-py/packages/tori-py-microservices[rabbitmq]"
```

The initial `0.1.0` package train is not published yet, so the explicit local
path matters. The `rabbitmq` extra adds `aio-pika`; the transport-neutral package
also supplies typed contracts, RPC and event runtimes, and the in-memory test
transport.

If you are starting directly at Part 3, create the same consumer project and add
the complete dependency set. First initialize and pin the project:

```text
git clone https://github.com/mikeoz32/tori-py.git
uv init --python 3.14 --bare task-api
cd task-api
uv python pin 3.14
```

Replace the generated project metadata before adding dependencies:

```toml
[project]
name = "task-api"
version = "0.1.0"
requires-python = ">=3.14,<3.15"
dependencies = []
```

Then install the complete source-checkout dependency set:

```text
uv add --editable "../tori-py/packages/tori-py[cli,testing]"
uv add --editable "../tori-py/packages/tori-py-cqrs-core"
uv add --editable "../tori-py/packages/tori-py-cqrs"
uv add --editable "../tori-py/packages/tori-py-microservices[rabbitmq]"
uv add --dev pytest pytest-asyncio
```

`uv add` updates both `pyproject.toml` and `uv.lock`. Do not install packages or
run the application with a separate `pip` environment.

## Replace the Package Tree

Replace the complete Part 2 `task_app/` directory. The old root-level
`models.py`, `state.py`, `handlers.py`, `http.py`, `app.py`, and `test_app.py`
do not remain in this version.

The complete project tree is:

```text
task-api/
  .python-version
  pyproject.toml
  uv.lock
  task_app/
    __init__.py
    contracts.py
    infrastructure.py
    testing.py
    test_system.py
    audit/
      __init__.py
      app.py
    gateway/
      __init__.py
      app.py
    tasks/
      __init__.py
      app.py
      handlers.py
      models.py
      services.py
      state.py
```

The four `__init__.py` files are empty package markers. The remaining files are
defined below.

## Step 1: Define the Wire Contract

Create `task_app/contracts.py`:

```python
--8<-- "examples/tori_py/tutorials/distributed_task_api/task_app/contracts.py"
```

`TASKS` and `AUDIT` are stable logical identities. They normalize to
`tutorial.tasks.v1` and `tutorial.audit.v1`; process names, hostnames, and replica
IDs do not become service identities.

The DTOs are explicit integration contracts:

- `Task` is the value returned by both RPC and HTTP;
- `CreateTaskV1`, `GetTaskV1`, and `ListTasksV1` are RPC payload schemas;
- `TaskCreatedV1` is a versioned integration event with an application event ID.

These DTOs are not the task service's local CQRS messages. Sharing the narrow
contract file does not share a repository, handler, domain model, or dependency
injection graph.

`@service_contract(TASKS)` associates the `TaskService` Protocol with one
service identity. Each `@rpc_call` declares a stable method alias, its payload
type, result annotation, and a positive finite two-second timeout. The generated
client proxy binds normal Python arguments into the declared DTO and decodes the
typed result. On the server, `@rpc(TaskService.create_task)` and its peers verify
that handler metadata matches the same contract.

One deadline covers transport readiness, request publication, publisher
confirmation, and reply waiting. A timeout stops the caller's wait; it does not
cancel a remote handler or prove that the remote write did not happen.

## Step 2: Add Shared Process Bootstrap

Create `task_app/infrastructure.py`:

```python
--8<-- "examples/tori_py/tutorials/distributed_task_api/task_app/infrastructure.py"
```

`rabbitmq_url()` reads `RABBITMQ_URL` without opening a connection. Its fallback
is useful only when a local broker permits `guest` from the host.

`serve()` is for the two broker-only roots. It creates one unstarted
`NestApplication`, starts its complete lifecycle, waits for process termination,
and always requests application shutdown in `finally`. The gateway is different:
its ASGI server drives startup and shutdown through lifespan.

## Step 3: Define Task-Local CQRS Messages

Create `task_app/tasks/models.py`:

```python
--8<-- "examples/tori_py/tutorials/distributed_task_api/task_app/tasks/models.py"
```

These dataclasses are process-local application messages. `CreateTask`,
`ListTasks`, `GetTask`, and `TaskCreated` are routed only by the task service's
in-memory CQRS buses. They are never encoded as RabbitMQ payloads.

The boundary translation is deliberate:

```text
CreateTaskV1 RPC DTO -> CreateTask local command
Task local result    -> Task RPC result
TaskCreated local event -> local TaskMetrics only
Task result          -> TaskCreatedV1 integration event
```

The local `TaskCreated` event and wire `TaskCreatedV1` event have different jobs.
The first coordinates an in-process reaction; the second is a versioned fact for
another service.

## Step 4: Add Task-Owned State

Create `task_app/tasks/state.py`:

```python
--8<-- "examples/tori_py/tutorials/distributed_task_api/task_app/tasks/state.py"
```

`TaskRepository` is the task service's write and query state. It assigns IDs and
normalizes read order, but remains in memory and disappears when that process
stops. The example demonstrates service ownership, not durable persistence or a
separate CQRS projection.

`TaskMetrics` is a process-local event reaction. Its condition gives the system
test a bounded completion signal; it is not a public API, broker metric, or
durable projection.

## Step 5: Implement Local Handlers

Create `task_app/tasks/handlers.py`:

```python
--8<-- "examples/tori_py/tutorials/distributed_task_api/task_app/tasks/handlers.py"
```

The command handler owns the task rule: trim the title, require 1-120 characters,
write through `TaskRepository`, and publish the local `TaskCreated` event. The
query handlers read only task-owned state. `CountTaskCreated` reacts through the
local event bus.

Decorators provide handler metadata and injectable provider metadata, but the
classes still have to be listed in the task module. ToriPy compiles exact command
and query mappings before this service accepts work.

Awaiting the local `EventBus.publish()` accepts the event into the local event
transport; it does not wait for `CountTaskCreated.handle()` to finish. The task
write and local metric update are not one transaction.

## Step 6: Coordinate CQRS and Integration Publication

Create `task_app/tasks/services.py`:

```python
--8<-- "examples/tori_py/tutorials/distributed_task_api/task_app/tasks/services.py"
```

`TaskApplicationService` is the boundary between RPC handlers, local CQRS, and
integration messaging. Reads execute local queries. A create executes the local
command first, then directly awaits `EventDispatcher.publish()` with:

- event alias `task-created`;
- payload schema version `1`;
- a fresh application `event_id`;
- `require_route=True`.

For RabbitMQ, a successful publish result means the broker confirmed the event
publication and at least one matching binding routed it. It does not mean that
the audit consumer was online, invoked, or committed an effect.

This direct write-then-publish sequence is intentionally **not an outbox**. The
task is already present if publication is rejected, times out, or has an
indeterminate outcome. A crash between the write and publish leaves a task with
no audit event. A crash after broker acceptance but before the service observes
the result can leave publication uncertain. There is no persistent record from
which this example can repair either gap.

## Step 7: Compose the Task Service

Create `task_app/tasks/app.py`:

```python
--8<-- "examples/tori_py/tutorials/distributed_task_api/task_app/tasks/app.py"
```

`TaskRpcController` translates wire DTOs into calls to
`TaskApplicationService`. Expected local errors become stable
`PublicRpcError` codes rather than serialized Python exceptions:

- `TaskTitleInvalid` becomes `invalid_request`;
- `TaskNotFound` becomes `not_found`.

`CqrsModule.for_root(global_=True)` creates process-local command, query, and
event buses. `MicroservicesModule.for_root(TASKS, ...)` gives this application
one logical service identity, discovers its explicitly registered RPC
controller, and supplies its source-bound `EventDispatcher`.

RabbitMQ derives one durable RPC queue and one wildcard binding for all three
methods:

```text
queue:   tori_py.rpc.tutorial.tasks.v1
binding: tutorial.tasks.v1.*
methods: tutorial.tasks.v1.create-task
         tutorial.tasks.v1.list-tasks
         tutorial.tasks.v1.get-task
```

Methods do not get separate queues. Replicas of the same task identity would be
competing consumers of this one queue, so in-memory task state would immediately
become inconsistent across replicas. Durable shared service-owned storage is
required before scaling this task service.

The create RPC returns only after this sequence completes:

```text
RPC request
  -> local CreateTask command
  -> in-memory task write
  -> local TaskCreated event accepted
  -> task-created.v1 integration publication confirmed and routed
  -> RPC Task reply
```

The gateway can then return HTTP `201`. That status means the remote write and
the directly awaited routed publication completed from the caller's observed
path. It does **not** wait for audit handling or prove an audit entry exists.

## Step 8: Build the Audit Service

Create `task_app/audit/app.py`:

```python
--8<-- "examples/tori_py/tutorials/distributed_task_api/task_app/audit/app.py"
```

The audit root has no HTTP routes or task RPC methods. Its controller consumes
the exact source identity, event alias, and payload schema from `contracts.py`.

`EventDispatchMode.SERVICE_POOL` with subscription `task-audit` creates one
durable queue for this destination service and logical effect. All replicas with
identity `tutorial.audit.v1` and that subscription would compete on the same
queue. Scaling replicas changes processing capacity; it does not broadcast one
copy to every replica.

RabbitMQ derives the queue from stable contract values:

```text
tori_py.event.tutorial.tasks.v1.task-created.v1--pool.tutorial.audit.v1.task-audit
```

`AuditLog.record()` counts every delivery but uses `setdefault(event.event_id,
event)` for the effect. Delivering the same application event twice therefore
leaves one entry. That demonstrates the required idempotency shape, but this
in-memory dictionary is not a production inbox:

- it is lost when the audit process restarts;
- separate replicas would have separate dictionaries;
- it is not committed atomically with a durable audit effect;
- retention and replay policy are undefined.

A production audit consumer needs a shared durable unique key such as
`(subscription, event_id)` committed in the same local transaction as the audit
effect.

## Step 9: Build the HTTP Gateway

Create `task_app/gateway/app.py`:

```python
--8<-- "examples/tori_py/tutorials/distributed_task_api/task_app/gateway/app.py"
```

The gateway preserves the HTTP routes while replacing direct bus access with an
injected `TaskService` Protocol. `ClientsModule.register_cluster()` supplies one
generic typed proxy under that Protocol token. The gateway is client-only: it
does not import `MicroservicesModule`, claim a service identity, or consume a
service queue.

The controller awaits each remote call. For `POST /tasks`, `@status(201)` is
applied only after `create_task()` returns its decoded `Task`. Msgspec validation
still rejects malformed HTTP bodies and converts the path value to `int` before
the proxy is called.

`GatewayErrorFilter` keeps distributed failures behind a stable HTTP boundary:

| RPC or transport outcome | HTTP status | Meaning at the gateway |
| --- | --- | --- |
| `invalid_request`, `not_found`, `conflict` | `400`, `404`, `409` | A correlated public application error arrived |
| Unknown service or unavailable connection/transport | `503` | The dependency route or transport is unavailable |
| RPC or transport timeout | `504` | The local finite wait expired |
| Outcome unknown or indeterminate | `502` | Acceptance or completion cannot be established |
| Protocol or other RPC client failure | `502` | The remote exchange did not produce a valid result |
| Unexpected error | `500` | Sanitized gateway failure |

A `502` or `504` does not prove that the task was not created. The framework does
not automatically resend accepted or indeterminate RPC. This contract has no
business idempotency key, so blindly retrying `POST /tasks` can create a second
task. Reconcile by an application identity before deciding to retry an unknown
outcome.

The exported `application = asgi(create_application)` lets Uvicorn own exact
startup and shutdown through ASGI lifespan. Startup opens the RabbitMQ client
transport and reply consumer before the gateway admits requests; shutdown closes
admission, pending client work, the reply route, channels, and connection under
the application shutdown budget.

## Step 10: Add the In-Memory Test Transport

Create `task_app/testing.py`:

```python
--8<-- "examples/tori_py/tutorials/distributed_task_api/task_app/testing.py"
```

Production composition uses keyed `RabbitMqTransport` references. The test
module provides in-memory server and client factories under the same public keyed
factory tokens. It does not fake controllers, RPC proxies, CQRS buses, codecs,
or application lifecycle.

`InMemoryTransportModule.for_root()` returns a deferred module with the same key
as the production transport reference. This makes it a valid explicit
replacement for one `RabbitMqModule` descriptor during test graph compilation.

## Step 11: Test All Three Roots

Create `task_app/test_system.py`:

```python
--8<-- "examples/tori_py/tutorials/distributed_task_api/task_app/test_system.py"
```

The test creates one `InMemoryBroker`, but it still compiles and starts three
independent ToriPy roots in dependency order:

1. The audit root is compiled first so its event subscription exists.
2. The task root is compiled next so its RPC service and publisher are ready.
3. The gateway root is compiled last with the production HTTP pipeline.

Each builder replaces only its exact production RabbitMQ descriptor:

```text
audit_rabbit   -> in-memory factories keyed by audit_transport
task_rabbit    -> in-memory factories keyed by task_transport
gateway_rabbit -> in-memory factories keyed by gateway_transport
```

The production modules remain otherwise unchanged. This is module replacement,
not a second application composition maintained only for tests.

The test drives real in-process ASGI requests through the gateway, typed RPC,
the task service, local CQRS, integration publication, and the audit handler. It
then republishes the same `TaskCreatedV1` value and proves that two deliveries
produce one audit entry. Finally, it closes applications in reverse order,
closes the broker, and verifies all application and transport lifecycle states.

Run it from the consumer project root:

```text
uv run pytest task_app/test_system.py -q
```

Expected result:

```text
1 passed
```

The repository copy can be verified from a ToriPy checkout with:

```text
uv run pytest examples/tori_py/tutorials/distributed_task_api/task_app/test_system.py -q
```

This is a three-root in-memory system test, not broker proof. It does not open a
socket, declare RabbitMQ quorum queues, exercise publisher confirms or mandatory
returns, prove reconnect behavior, test process isolation, or validate broker
redelivery and dead-letter topology. Keep real RabbitMQ acceptance tests as a
separate layer.

## Start RabbitMQ Locally

Start RabbitMQ 4 with its management UI. These credentials and plain AMQP are
for local development only:

```text
docker run --detach --rm --name tori-py-rabbitmq --hostname tori-py-rabbitmq --publish 5672:5672 --publish 15672:15672 --env RABBITMQ_DEFAULT_USER=tutorial --env RABBITMQ_DEFAULT_PASS=tutorial rabbitmq:4-management
```

Wait until the broker responds:

```text
docker exec tori-py-rabbitmq rabbitmq-diagnostics -q ping
```

The management UI is at `http://127.0.0.1:15672` with `tutorial` / `tutorial`.
The Python processes use:

```text
amqp://tutorial:tutorial@localhost:5672/
```

The mutable `rabbitmq:4-management` tag is convenient locally. Pin an approved
version or image digest in reproducible deployment configuration.

## Run the Three Processes

Open three terminals in the consumer project. Start them in this order so the
audit binding exists before the task service can publish, and the task RPC queue
exists before the gateway accepts HTTP traffic.

### 1. Audit Service

=== "PowerShell"

    ```powershell
    $env:RABBITMQ_URL = "amqp://tutorial:tutorial@localhost:5672/"
    uv run python -m task_app.audit.app
    ```

=== "Bash"

    ```bash
    RABBITMQ_URL="amqp://tutorial:tutorial@localhost:5672/" \
      uv run python -m task_app.audit.app
    ```

Wait for startup to complete before continuing. This declares and consumes the
service-pool queue whose stable name ends in the `task-audit` subscription.

### 2. Task Service

=== "PowerShell"

    ```powershell
    $env:RABBITMQ_URL = "amqp://tutorial:tutorial@localhost:5672/"
    uv run python -m task_app.tasks.app
    ```

=== "Bash"

    ```bash
    RABBITMQ_URL="amqp://tutorial:tutorial@localhost:5672/" \
      uv run python -m task_app.tasks.app
    ```

This process starts its local CQRS buses, the task RPC consumer, and its
integration event dispatcher.

### 3. HTTP Gateway

=== "PowerShell"

    ```powershell
    $env:RABBITMQ_URL = "amqp://tutorial:tutorial@localhost:5672/"
    uv run uvicorn task_app.gateway.app:application --lifespan on --host 127.0.0.1 --port 8000
    ```

=== "Bash"

    ```bash
    RABBITMQ_URL="amqp://tutorial:tutorial@localhost:5672/" \
      uv run uvicorn task_app.gateway.app:application \
        --lifespan on --host 127.0.0.1 --port 8000
    ```

The gateway starts its typed client cluster and exclusive reply route before
Uvicorn completes lifespan startup.

You can inspect the two durable consumer queues from another terminal:

```text
docker exec tori-py-rabbitmq rabbitmqctl list_queues name consumers
```

## Exercise the HTTP Contract

Create a task. In PowerShell, pipe the JSON body so `curl.exe` receives it
without shell quote rewriting:

```powershell
'{"title":"  Ship the distributed tutorial  "}' |
  curl.exe -i -X POST "http://127.0.0.1:8000/tasks" `
    -H "content-type: application/json" `
    --data-binary '@-'
```

The relevant response is:

```text
HTTP/1.1 201 Created
content-type: application/json

{"id":1,"title":"Ship the distributed tutorial"}
```

At this point the remote task write and routed event publication have completed.
The audit handler may still be pending. The response does not wait for audit
completion.

Read through the same public API:

```powershell
curl.exe -i "http://127.0.0.1:8000/tasks"
curl.exe -i "http://127.0.0.1:8000/tasks/1"
curl.exe -i "http://127.0.0.1:8000/tasks/999"
```

The response bodies are:

```text
HTTP/1.1 200 OK
[{"id":1,"title":"Ship the distributed tutorial"}]

HTTP/1.1 200 OK
{"id":1,"title":"Ship the distributed tutorial"}

HTTP/1.1 404 Not Found
{"type":"about:blank","title":"Not Found","status":404,"detail":"Task was not found.","instance":"/tasks/999"}
```

Exercise remote business validation:

```powershell
'{"title":"   "}' |
  curl.exe -i -X POST "http://127.0.0.1:8000/tasks" `
    -H "content-type: application/json" `
    --data-binary '@-'
```

The task service raises its local error, the RPC boundary returns the public
`invalid_request` code, and the gateway maps it to:

```text
HTTP/1.1 400 Bad Request
content-type: application/problem+json

{"type":"about:blank","title":"Bad Request","status":400,"detail":"After trimming, the task title must contain 1-120 characters.","instance":"/tasks"}
```

Bash users can run the equivalent create request with:

```bash
curl -i -X POST "http://127.0.0.1:8000/tasks" \
  -H "content-type: application/json" \
  -d '{"title":"Ship the distributed tutorial"}'
```

## Understand At-Least-Once Behavior

Both durable RPC execution and reliable event consumption are at least once.
They have different duplicate boundaries:

- An RPC request can execute again after a connection failure leaves reply or
  request settlement uncertain. This example has no create-operation
  idempotency key, so a duplicate execution can create another task.
- An event can be delivered again after `AuditLog.record()` succeeds but its ACK
  is lost. The event's stable `event_id` lets the audit effect become a no-op for
  that duplicate within this one process lifetime.
- A client timeout or cancellation only stops local waiting. It does not cancel
  a task handler that already started.
- The RPC transport does not automatically resend an accepted or indeterminate
  request. `RpcOutcomeUnknownError` requires reconciliation and an application
  decision, not a blanket retry.
- A publisher confirm and `routed=True` establish broker acceptance and a
  matching binding, not consumer completion.

Transport message and correlation IDs are not business idempotency keys. The
`event_id` in `TaskCreatedV1` is application-owned specifically so a consumer can
deduplicate publication/redelivery of the same fact.

## Shut Down Deliberately

Stop new HTTP admission first, then producers, then consumers:

1. Press `Ctrl+C` in the gateway terminal and wait for Uvicorn lifespan shutdown.
2. Press `Ctrl+C` in the task service terminal and wait for `serve()` to finish.
3. Press `Ctrl+C` in the audit terminal and wait for `serve()` to finish.
4. Stop the disposable broker:

```text
docker stop tori-py-rabbitmq
```

Because the container was started with `--rm`, Docker removes it after stopping.
The RabbitMQ queues and all in-memory task and audit state disappear.

Normal application shutdown first closes admission, then drains accepted work
within a bounded shared budget, stops consumers and CQRS buses, closes reply
routes and transports, and finally closes broker connections. Forced process or
container termination can interrupt those steps, so deployment grace periods
must exceed the application shutdown and connection cleanup budgets.

## Production Hardening and Next Techniques

The smallest production correction for write/publication consistency is an
application-owned transactional outbox:

```text
task row + outbox row with stable event_id (one database transaction)
  -> at-least-once relay calls EventDispatcher.publish()
  -> mark published only after a definitive publisher result
  -> audit inbox/dedup row + durable audit effect (one local transaction)
  -> successful handler return permits consumer ACK
```

An outbox closes the current write-before-publish loss window, but it still
permits duplicate publication when a relay crashes after publish and before
marking the row. The audit service therefore still needs durable idempotency.
Indeterminate relay outcomes need reconciliation policy, not an assertion of
success or an unbounded resend loop.

Also add a stable business idempotency key and persisted result for effectful
create RPC, durable task and audit stores, versioned migrations, authentication
and authorization, TLS and least-privilege broker credentials, bounded capacity,
readiness, metrics, tracing, dead-letter operations, retention, and real-broker
failure tests.

Continue with [Microservice Operations](../techniques/microservices/operations.md)
for outbox/inbox, idempotency, monitoring, recovery, and shutdown policy. Read
[RPC](../techniques/microservices/rpc.md) for deadline and unknown-outcome
semantics, [Events](../techniques/microservices/events.md) for subscription and
deduplication policy, [Clients and Contracts](../techniques/microservices/clients-and-contracts.md)
for typed proxy evolution, and [RabbitMQ](../techniques/microservices/rabbitmq.md)
before changing topology or production broker configuration.
