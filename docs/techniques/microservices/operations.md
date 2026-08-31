# Operations

Operate ToriPy microservices as at-least-once distributed systems. Readiness,
publisher acceptance, consumer settlement, database commit, and caller
observation are separate facts that can fail independently.

## Production Checklist

- Use RabbitMQ 4.0 or newer and the RabbitMQ package extra.
- Use `amqps://` with `tls=True` outside trusted local development.
- Install trusted CA certificates; never disable certificate verification.
- Assign per-service credentials/vhosts and least-privilege resource/topic
  permissions.
- Keep service, method, event, subscription, and reliable-instance aliases
  stable across deployments.
- Apply database/schema migrations before message consumers become ready.
- Set finite RPC, connection, heartbeat, concurrency, prefetch, pending-map,
  queue, retry, and shutdown bounds.
- Provision DLX retention, access controls, alerts, quarantine, and replay
  procedures before enabling reliable consumers.
- Define RPC idempotency and event inbox policy for every durable side effect.
- Test topology and network failures against a real broker, not only in memory.

## Readiness And Liveness

Liveness answers whether the process/event loop should be restarted. Readiness
answers whether it can currently accept its intended traffic.

Application startup returns only after inbound service topology is prepared,
work-scope admission is open, and required server consumers are active. An RPC
client cluster also prepares and consumes its exclusive reply route before it
admits calls.

Outbound event-publisher topology is different. `EventDispatcher` starts a
client transport with reply reception disabled, and the RabbitMQ event exchange
is declared lazily by the first `publish()` for that source identity. Startup
therefore does not prove event-exchange configure permission or declaration
compatibility. Treat the first event publication, and every publication after
recovery, as a topology and permission failure boundary.

During recovery, use current state rather than a historical successful
operation. These signals are conjunctive rather than interchangeable:

- `RabbitMqConnectionManager.status == RabbitMqStatus.READY`;
- server/client `TransportStatus.RUNNING`;
- `EventDispatcher.accepting` for its local lifecycle admission gate;
- application-specific database/dependency checks where the service contract
  requires them.

`EventDispatcher.accepting` alone is not transport readiness and does not mean
that the lazily declared event exchange has been validated.

Do not publish a probe message as the only readiness check. A confirm proves
broker acceptance, not active consumers. A durable service queue can remain
routable with zero replicas. RabbitMQ consumer count and queue depth are useful
operator signals, but the framework has no live membership registry.

An API gateway may perform bounded health RPCs to required dependencies, as the
multi-process example does. Such checks consume real queue/client capacity and
must have finite deadlines; do not confuse them with a guarantee that the next
business call will succeed.

## Monitoring

The package exposes typed outcomes and bounded status streams, but does not ship
a metrics exporter or logging backend. Instrument these signals in application
pipeline components and lifecycle providers, and collect queue/consumer facts
from RabbitMQ's monitoring interfaces.

Monitor rates, gauges, and latency distributions for:

- RabbitMQ manager and transport status transitions by service/version;
- startup/recovery duration and topology declaration failures;
- active consumers, queue depth, oldest-message age, and unacknowledged count;
- service concurrency/prefetch saturation and accepted task count;
- pending RPC count, capacity rejection, timeout, outcome-unknown, unknown
  service, remote error code, and protocol failure counts;
- publisher-confirm latency, NACKs, mandatory returns, pre-write timeouts, and
  indeterminate publications;
- handler, work-scope cleanup, reply, settlement, and total latency;
- delivery attempts/redelivery, retry queue depth, dead-letter depth, and
  messages approaching retention/length limits;
- outbox pending age/attempts and inbox duplicate rate;
- graceful shutdown duration, forced cancellation, lingering callback/task, and
  resource-close failures.

Metric labels must be bounded: namespace, service, contract version, method or
event alias, schema version, subscription, dispatch mode, status, and a stable
outcome/error code. Never label metrics with message/correlation/causation IDs,
reply tokens, payload values, user identifiers, credentials, exception text, or
arbitrary headers.

Structured logs may carry IDs for correlation under retention/access policy, but
must not contain credentials, AMQP URLs with passwords, reply tokens, payloads,
access tokens, or unsanitized remote/internal exception details. Propagate
validated `traceparent`/`tracestate` explicitly if used; ambient HTTP headers and
`ContextVar` state are not copied automatically.

## Capacity And Backpressure

Tune these bounds together:

| Bound | Effect when exhausted |
| --- | --- |
| `MicroservicesOptions.max_concurrency` | Limits active handler invocations per replica |
| `max_inflight_deliveries` | Bounds aggregate consumer prefetch and must be at least concurrency |
| number of RPC/event consumers | Must fit at least one prefetch slot each or startup fails |
| `ServiceClusterOptions.max_pending_requests` | Rejects new calls before publication |
| client `max_pending_replies` | Bounds reply transport QoS/queueing; module-created RabbitMQ clients currently use a fixed value of 10,000 |
| envelope/header/collection limits | Reject malformed or oversized input before expensive work |
| retry/DLX queue length | Last-resort broker safety bound, not normal operating capacity |

Normal keyed `RabbitMqTransport` composition does not expose a
`max_pending_replies` option: `RabbitMqClientTransportFactory` constructs the
public low-level client with its 10,000-entry default. Keep
`ServiceClusterOptions.max_pending_requests` at or below that value. Selecting a
different reply bound currently requires explicitly constructing the low-level
client or supplying a custom client factory.

One service queue and service-wide semaphore are shared by all RPC methods.
Adding replicas increases competing-consumer capacity but does not promise strict
round robin. Monitor saturation before increasing prefetch; excessive prefetch
can pin work to a slow replica and increase redelivery after failure.

`max_accepted_rpc_timeout` limits the server's accepted backlog horizon. Keep
client maxima at or below the service's policy and synchronize clocks. Long
business workflows should not be modeled as very long synchronous RPC calls.

## At-Least-Once Boundaries

RPC can execute more than once when a connection fails after a durable effect or
reply but before request ACK. Events can execute more than once when a consumer
commits then loses settlement. Event publication can duplicate when an outbox
relay publishes but crashes before recording success.

Therefore:

- `message_id` is a transport delivery identity, not a business key;
- `correlation_id` pairs RPC request/reply and supports tracing, not
  deduplication;
- caller timeout/cancellation does not cancel or roll back remote work;
- publisher confirm does not prove a handler ran;
- consumer ACK does not make a producer database transaction atomic;
- a `retryable` remote error flag does not trigger automatic resend;
- accepted/indeterminate RPC is never automatically retried by the framework.

For effectful RPC, include a stable application idempotency key in the request
DTO. Persist a unique decision/result under the operation's business scope in
the same transaction as the effect. A later application-approved retry can then
return or reconcile the original outcome. Do not generate a new key per retry.

## Outbox And Inbox Boundary

Reliable integration event flow is application-owned:

```text
local state change + outbox insert (one database transaction)
  -> at-least-once outbox relay
  -> EventDispatcher publisher confirm
  -> consumer inbox/dedup record + local effect (one database transaction)
  -> successful handler return
  -> consumer ACK
```

The outbox record should contain a stable application event ID, event/schema
identity, original occurrence time, bounded payload, and relay state/attempt
facts. The relay:

1. Reads pending records under an application-defined concurrency/lease policy.
2. Calls `EventDispatcher.publish()`, preserving `occurred_at` and carrying the
   stable application event ID in the integration contract.
3. Marks the row published only after a definitive publication receipt.
4. Leaves indeterminate rows for reconciliation or deliberate retry policy.

A crash between steps 2 and 3 produces a duplicate, which is expected. Separate
dispatcher calls create separate transport message IDs, so consumers deduplicate
by the stable application event ID.

The inbox/effect transaction uses a unique key such as
`(subscription, application_event_id)`. A duplicate that already committed is a
successful no-op and can be ACKed. Keep inbox retention at least as long as the
maximum producer replay/reconciliation horizon. Deleting dedup records early
re-enables effects.

ToriPy CQRS remains local/in-process. Translate integration DTOs to local
commands/queries explicitly; do not publish internal CQRS objects, ORM rows,
domain events, or event-sourcing records as wire contracts automatically.

The runnable orders service inserts its order and outbox row atomically. Its
relay publishes `order-created`; the notifications service stores a unique
outbox event ID with the local notification. This is an example boundary, not
built-in outbox/inbox infrastructure.

## Failure Runbook

### Connection Recovering

- Mark dependency readiness false while the manager/transport is recovering.
- Check broker reachability, TLS trust, credentials, vhost limits, and alarms.
- Wait for topology redeclaration and consumer/reply-route restoration.
- Treat pending calls from the lost reply generation as outcome unknown.
- Do not manually mass-retry effectful RPC without idempotency/reconciliation.

### Topology Failure

- Compare exchange/queue type, durability, exclusivity, TTL, DLX, and arguments.
- Treat inequivalent topology as a migration/deployment issue.
- Drain/migrate/delete resources only through an approved operational plan.
- Never expect the adapter to mutate an existing queue type automatically.

### Retry Or DLX Growth

- Identify the bounded source service/event/schema/subscription and stable error
  class without putting payload data in metric labels.
- Stop or scale down a poison-producing consumer if retries amplify load.
- Inspect protected payloads only under the service's access policy.
- Fix schema/configuration/code or isolate the producer before replay.
- Replay deliberately with an application decision and preserved application
  identity; a DLX is not an implicit retry worker.

### RPC Timeout Or Unknown Outcome Spike

- Separate no-route, queue backlog, readiness wait, confirm delay, reply loss,
  and handler latency.
- Check queue consumer count and oldest-message age, not only publish success.
- Reconcile business state for accepted/unknown commands before retrying.
- Scale replicas or reduce upstream admission only after finding the constrained
  capacity domain.

## Graceful Shutdown

On termination, ToriPy closes publication/intake admission, cancels consumers,
drains accepted callbacks and work scopes under one decreasing application
deadline, then closes reply routes/channels/connections. Work exceeding the
budget is cancelled; uncertain deliveries are requeued only when safe or left
unsettled for broker redelivery.

Set the orchestrator grace period above the application shutdown timeout and
connection cleanup allowance. Monitor forced cancellation and lingering tasks.
Do not swallow `CancelledError` in handlers or lifecycle providers, and do not
start untracked cleanup after public shutdown returns.

## Multi-Process Example

The repository example runs four independent applications plus RabbitMQ and
three PostgreSQL databases:

- `catalog`: catalog RPC and local CQRS;
- `orders`: order RPC, catalog RPC client, local CQRS, and outbox relay;
- `notifications`: durable service-pool event consumer with deduplication;
- `api-gateway`: HTTP-only typed RPC client with no database.

Start it from the repository root:

```text
docker compose -f examples/tori_py/microservices_app/compose.yaml up --build
```

Exercise the complete flow with the uv-managed Python environment:

```text
uv run python -m examples.tori_py.microservices_app.smoke
```

Stop it and delete example volumes:

```text
docker compose -f examples/tori_py/microservices_app/compose.yaml down -v
```

The Compose file uses development credentials and plain AMQP. It is not a
production deployment template.

## Verification

Run focused and full package checks from the repository root:

```text
uv run pytest packages/tori-py-microservices/tests -q
uv run pytest examples/tori_py/microservices examples/tori_py/microservices_app -q
uv run ruff check .
uv run ruff format --check .
uv run python packages/tori-py-microservices/scripts/verify_docs.py
```

Docker-backed RabbitMQ tests require the package test Compose environment and
its configured broker URL; keep those results with production-release evidence.
