# RabbitMQ

The RabbitMQ adapter supplies one keyed, lifecycle-managed connection root and
transport factories for RPC, events, and replies. RabbitMQ 4.0 or newer is
required for the documented queue and delivery-limit behavior.

## Install And Compose

```text
uv add "tori-py-microservices[rabbitmq]"
```

One `RabbitMqModule` root owns one robust connection. `RabbitMqTransport` refers
to that root by key and carries no credentials in handler metadata:

```python
from tori_py import module
from tori_py_microservices import (
    ClientsModule,
    MicroservicesModule,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    ServiceClusterOptions,
    ServiceIdentity,
)

ORDERS = ServiceIdentity("shop", "orders", 1)

rabbitmq = RabbitMqModule.for_root(
    RabbitMqOptions(
        "amqps://orders:password@rabbitmq.example/orders",
        tls=True,
        connection_name="orders-v1",
    )
)
transport = RabbitMqTransport()
service = MicroservicesModule.for_root(
    ORDERS,
    transport=transport,
    imports=(rabbitmq,),
)
clients = ClientsModule.register_cluster(
    transport,
    imports=(rabbitmq,),
    options=ServiceClusterOptions(default_rpc_timeout=3, max_rpc_timeout=10),
)


@module(imports=(service, clients))
class OrdersApplication:
    pass
```

Use distinct keys when one process intentionally needs different RabbitMQ roots:
`RabbitMqModule.for_root(..., key="audit")`, `RabbitMqTransport("audit")`, and a
matching client/service import. One application may have several client roots,
but still at most one logical `MicroservicesModule` service identity.

## Connection Options

`RabbitMqOptions` is immutable and validates:

| Option | Default | Purpose |
| --- | --- | --- |
| `url` | required | Exactly one `amqp://` or `amqps://` endpoint |
| `connection_name` | `tori-py-microservices` | Broker-visible diagnostic name |
| `heartbeat` | `60` seconds | Connection liveness bound |
| `connection_timeout` | `10.0` seconds | Connect/recovery-listener/resource-operation bound |
| `reconnect_interval` | fixed `5.0` seconds | Robust connection retry interval |
| `tls` | `False` | Must exactly match the URL scheme |
| `rpc_exchange` | `tori_py.rpc` | Durable shared RPC topic exchange |
| `reply_queue_expires_ms` | `300000` | Unused exclusive reply queue expiry |
| `retry_delay_ms` | `1000` | Delayed retry queue TTL |
| `max_delivery_attempts` | `5` | Framework/broker attempt bound |

Credentials are redacted from `repr(options)`. Keep them in secret-backed
deployment configuration, not source or logs.

For TLS, use `amqps://` with `tls=True`. Plain `amqp://` requires `tls=False`.
The adapter rejects mismatches and URL query flags that override managed
heartbeat, timeout, connection name, SSL, or certificate verification settings,
including `no_verify_ssl`. Install the required CA trust in the runtime image;
do not disable verification.

Endpoint rotation across several URLs and externally supplied connection
ownership are not provided. The robust connection reconnects to its configured
endpoint.

## Resource Ownership

Each root uses one robust socket and three separate channels:

- consumer channel with manual acknowledgement and QoS;
- publisher channel with publisher confirms and mandatory-return handling;
- reply channel for exclusive reply queues and correlation.

Delivery tags are channel-local. The adapter never settles an old tag on a new
channel. Framework declarations and consumer registrations use `robust=False`;
the framework, not aio-pika replay, coordinates declaration and intake after a
reconnect.

## RPC Topology

For `ServiceIdentity("shop", "orders", 1)`:

```text
exchange:      tori_py.rpc (durable topic)
primary queue: tori_py.rpc.shop.orders.v1 (durable quorum)
binding:       shop.orders.v1.*
request key:   shop.orders.v1.<method>
```

There is one primary service queue and one wildcard binding, not a queue or
binding per method. Every replica consumes the same queue with equal priority,
manual ACK, bounded prefetch, no exclusive consumer, and no single-active-
consumer setting.

Each client cluster owns one generated route matching `reply.<32 lowercase hex
characters>`. It is both the routing key and the name of a classic,
non-durable, exclusive, auto-delete reply queue with `x-expires` from
`reply_queue_expires_ms`. A replacement route is generated after reconnect; old
routes are never reused.

Requests and events use persistent delivery mode. Replies are transient because
the exclusive route and caller deadline define their useful lifetime.

## Event Topology

Every source service publishes to one durable topic exchange:

```text
tori_py.events.<namespace>.<source>.v<source_contract_version>
```

Handlers bind the exact `<event>.v<schema_version>` key. Primary queue names are:

```text
tori_py.event.<source-label>.<event>.v<schema>--pool.<destination-label>.<subscription>
tori_py.event.<source-label>.<event>.v<schema>--singleton.<subscription>
tori_py.event.<source-label>.<event>.v<schema>--broadcast.<destination-label>.<subscription>.<instance>
```

Queue properties:

| Subscription | Queue |
| --- | --- |
| Service pool | Durable quorum |
| Singleton | Durable quorum |
| Ephemeral broadcast | Classic, non-durable, exclusive, auto-delete |
| Reliable broadcast | Durable classic queue, exclusive consumer |

Reliable broadcast currently applies `x-expires=604800000` (seven days) and
`x-message-ttl=86400000` (one day). These finite retention values prevent
unbounded orphan/backlog retention but do not replace operator cleanup and
capacity planning.

## Retry And Dead-Letter Topology

Every reliable primary queue is accompanied by deterministic retry and
dead-letter resources:

```text
primary queue
  -- retryable failure --> dedicated retry exchange --> .retry queue
  -- delay expires ----------------------------------> primary exchange
  -- terminal/attempt limit ------------------------> tori_py.dead-letter --> .dead-letter queue
```

The primary durable quorum queue declares:

- `x-delivery-limit=max_delivery_attempts`;
- dead-letter exchange `tori_py.dead-letter`;
- dead-letter routing key equal to the primary queue name.

The durable classic retry queue declares:

- `x-message-ttl=retry_delay_ms`;
- dead-letter exchange back to the primary exchange;
- `x-max-length=10000`;
- `x-overflow=reject-publish`.

The durable quorum dead-letter queue declares `x-max-length=10000` and
`x-overflow=drop-head`. Alert before either bound is reached: these are safety
bounds, not retention objectives.

The retry exchange is `<primary-queue>.retry` when that fits RabbitMQ's
127-byte exchange-name limit; otherwise it is a deterministic
`tori_py.retry.<sha256>` name. Queue identity is never shortened.

For retry, the adapter publishes the same transport message ID and incremented
broker-visible attempt metadata to the delayed path. It ACKs the original only
after retry publication is confirmed. A retry NACK/unroutable result becomes
terminal; confirm uncertainty fences the connection and leaves the original
outcome unsettled. Immediate unbounded requeue loops are not used.

Ephemeral broadcast intentionally has no durable retry/DLX path. RPC does not
automatically retry an accepted or uncertain application call; the topology is
not permission for client resends.

## Publisher Outcomes

The confirm channel distinguishes:

- broker ACK: accepted publication;
- broker NACK/reject: `TransportRejectedError`;
- mandatory return: `TransportUnroutableError`;
- cancellation before broker write: `TransportTimeoutError`;
- connection/channel loss or cancellation after write with no definitive
  confirm: `TransportIndeterminateError`.

An indeterminate publication fences the current connection generation so stale
delivery/reply state cannot be mistaken for success. A reply can arrive before
the request's confirm completes; a validated reply wins that race and suppresses
unnecessary fencing for that publication.

## Recovery And Readiness

`RabbitMqConnectionManager` reports `CREATED`, `CONNECTING`, `READY`,
`RECOVERING`, `FAILED`, and `CLOSED`. Server/client transports separately report
`TransportStatus` transitions.

On connection loss the manager increments its generation and tells transports
to close admission. Recovery preserves this safety order:

1. keeps admission closed and cancels, drains, or fences old-generation callback,
   settlement, and reply state;
2. re-declares and verifies prepared server topology;
3. restarts server consumers that were previously running;
4. creates and consumes a new client reply route;
5. reports ready only after every recovery listener succeeds.

An event-publisher-only client has no prepared event exchange to replay during
this barrier. Its source exchange remains a lazy declaration performed by
`publish_event()` after recovery, so manager readiness is not proof that the
publisher's exchange permissions or declaration will succeed.

Pending calls tied to a lost reply route fail with `RpcOutcomeUnknownError` and
are never republished. Unsettled server deliveries may redeliver with the same
message ID. A topology mismatch is `RabbitMqTopologyError` and blocks readiness;
the adapter never migrates queue type or arguments automatically.

Readiness is the current manager/transport state, not one successful publish.
For a keyed root, inject `RabbitMqConnectionManager` through the public
`rabbitmq_manager_token(key)` when an application health component needs to
observe `RabbitMqStatus.READY`.

## Shutdown

Shutdown closes admission before resource teardown:

1. Cancel consumers and await broker cancellation acknowledgement.
2. Cross the callback scheduling fence.
3. Drain accepted callback handoffs and runtime-owned message tasks.
4. Let work scopes clean up and settle while the shared deadline remains.
5. Cancel remaining work and safely requeue/leave unsettled when required.
6. Close reply consumers, channels, and the owned connection.

Cancellation-resistant callbacks or resource close failures are reported; the
adapter does not claim clean shutdown while work remains. Set deployment grace
periods longer than the ToriPy application shutdown budget plus broker/network
close allowance.

## Broker Permissions

Use one credential and vhost permission set per service/process. Grant only the
`configure`, `write`, and `read` patterns required for its exchanges, queues,
bindings, retry/DLX resources, and reply route. If applications share
`tori_py.rpc`, ordinary resource permissions allow writes to the exchange;
RabbitMQ topic permissions are required to constrain target routing keys.

Operator-provisioned shared exchanges can remove application configure rights,
but declarations must remain equivalent. Never trust a routing key, header, or
reply route as authorization; enforce application authorization in guards or the
application layer.

See [Operations](operations.md) for monitoring and recovery runbooks.
