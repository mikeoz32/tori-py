# MS9: Clustered Event Dispatch

## Status

Implemented. The root-owned application-facing `EventDispatcher`, RabbitMQ
event routing, topology, transport mechanics, and event-mode tests for
`SERVICE_POOL`, `SINGLETON`, ephemeral `BROADCAST`, and reliable `BROADCAST` are
implemented, including bounded delayed retry and DLX paths. The dispatcher core
is proven with in-memory, fake keyed-adapter composition, application DI, and
real RabbitMQ tests. Reliable-broadcast restart and the complete real-broker
cardinality matrix are proven, so the MS9 exit criteria are met.

## Purpose

Implement consumer-owned RabbitMQ event topology for `SERVICE_POOL`,
`SINGLETON`, and `BROADCAST` without coupling the producer dispatcher to
delivery modes.

## Producer Topology

```text
exchange: nestpy.events.<namespace>.<source>.v<contract_version>
type:     topic
routing:  <event_alias>.v<schema_version>
```

- `EventDispatcher` inherits source identity from the local service root.
- Caller supplies event alias, schema version, payload, and explicit safe
  metadata.
- Dispatcher never selects consumer mode, destination service, queue, or
  subscription.
- Zero subscribers is valid unless `require_route` is explicitly selected.
- Dispatcher uses mandatory publication to return an accurate routing result and
  suppresses the unroutable error only when zero subscribers are permitted.
- Publisher confirmation proves broker acceptance only.
- Event messages use persistent AMQP delivery mode.

## Common Consumer Contract

- `@event_handler` declares complete `ServiceIdentity` source, event, schema
  version, mode, stable subscription, and reliability.
- Source namespace, service, and contract version select the source exchange;
  schema version independently selects the event payload contract.
- Handler queue binds to the exact source exchange and
  `<event_alias>.v<schema_version>` routing key.
- Each delivery receives an independent work scope.
- ACK occurs only after pipeline and scope completion.
- Retry/reject policy is bounded and compatible with configured DLX policies.
- Different subscriptions never share settlement state.
- Per-consumer prefetch allocations sum with RPC prefetch to no more than the
  replica's `max_inflight_deliveries`; an oversized consumer set fails startup.

## SERVICE_POOL

Queue identity:

```text
<event_queue_prefix>--pool.<destination_namespace>.<destination>.v<destination_version>.<subscription>
```

`<event_queue_prefix>` is
`nestpy.event.<namespace>.<source>.v<source_version>.<event>.v<schema_version>`.

- Queue is durable and quorum by default.
- All replicas of one destination service/subscription compete on the same
  queue.
- One replica receives each delivery attempt.
- Two subscriptions for one event create two queues and both receive the event.
- Queue identity survives process restarts and replica scaling.

## SINGLETON

Queue identity:

```text
<event_queue_prefix>--singleton.<subscription>
```

- Queue is durable and quorum by default.
- Consumers from any service declaring the exact subscription compete.
- One consumer receives each delivery attempt globally for that subscription.
- Explicit subscription is mandatory and defines payload/effect compatibility.
- This is message distribution, not leader election or a general distributed
  lock.

## BROADCAST

Queue identity:

```text
<event_queue_prefix>--broadcast.<destination_namespace>.<destination>.v<destination_version>.<subscription>.<instance_identity>
```

Ephemeral broadcast:

- generated process identity;
- classic exclusive auto-delete queue;
- no durable backlog while offline;
- intended for cache invalidation, presence, and local wakeups.

Reliable broadcast:

- explicit stable instance identity;
- durable classic queue;
- mandatory exclusive consumer to reject duplicate live identity;
- explicit retention/expiry and orphan cleanup policy;
- deployment contract suitable for stable StatefulSet-like identities only.

Default generated identity with `reliable=True` is invalid because restart would
orphan a durable queue and lose the logical instance continuation.

## Failure Classification

- Decode/schema/permanent validation failure: reject without requeue to DLX.
- Explicit retryable error: bounded retry/requeue.
- Unexpected ordinary exception: bounded retry under queue policy.
- Explicit terminal rejection: reject without requeue.
- Cancellation/connection loss: unsettled and eligible for redelivery.
- Settlement uncertainty: replace channel and retain indeterminate diagnostics.

Immediate unbounded requeue loops are invalid. A retryable delivery is published
with the same message identity and broker-visible attempt count to a dedicated,
bounded delayed-retry queue. The original delivery is ACKed only after that
publication is confirmed; the retry queue dead-letters back to the primary
exchange after its finite delay. Reaching the configured maximum attempt count
rejects the delivery to the dead-letter path.

Retry exchange names use `<queue>.retry` while that value fits the broker's
127-byte exchange-name limit. Longer queue identities use a deterministic
`nestpy.retry.<sha256>` exchange name without weakening queue identity.

RabbitMQ 4.0 or newer is required. Durable quorum primary queues also declare a
finite delivery limit as a broker-side bound. Reliable broadcast classic queues
use the same framework-owned retry/DLX topology and require a stable instance
identity.

## Tests

- Exact exchanges, queue names, bindings, types, and durability.
- Two replicas in one service pool receive one total event.
- Two services/subscriptions each receive one event.
- Two methods with distinct subscriptions receive independently.
- Singleton consumers across several services receive one total event.
- Three ephemeral broadcast replicas each receive one event.
- Ephemeral broadcast misses events while offline.
- Reliable broadcast retains events across restart with stable identity.
- Duplicate reliable broadcast identity fails or remains unavailable.
- Failure/retry/DLX behavior and no cross-subscription retries.
- Producer with zero subscribers and explicit `require_route` behavior.
- Quiesce and redelivery during replica shutdown.

Implemented dispatcher acceptance additionally proves generated IDs/timestamps,
caller-supplied safe metadata, immutable root-derived source/routing, no reply
consumer, pre-start/post-quiesce rejection, accepted-publication draining,
deadline cancellation, bounded shutdown with cancellation-resistant publication,
owned transport close, exact keyed client-factory injection, and two distinct
subscriptions receiving once. The Docker producer test uses `EventDispatcher`
rather than a raw transport `Publication`.

Docker-backed completion acceptance additionally proves an exact twelve-queue
matrix for two durable service pools, one global singleton, and three ephemeral
broadcast instances; one delivery per pool, one global singleton delivery, and
one delivery per live broadcast instance; offline ephemeral loss; duplicate
reliable instance rejection; and reliable delivery retained across consumer
restart with a stable instance identity.

## Exit Criteria

- Broker queue topology alone produces the documented pool, singleton, and
  broadcast cardinality.
- Producer code remains independent of consumer mode and destination topology.
