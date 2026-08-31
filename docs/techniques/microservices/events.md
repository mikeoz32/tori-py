# Events

Events are one-way facts published by one service identity and consumed through
consumer-owned subscriptions. The producer defines the fact; each consumer
defines its own queue cardinality, reliability, retry, and idempotent effect.

## Event Identity

An event is identified by:

- the complete source `ServiceIdentity`;
- a stable event alias;
- an independent positive payload schema version.

For source `ServiceIdentity("shop", "orders", 1)`, event `order-created`, and
schema `1`, RabbitMQ uses:

```text
exchange:    tori_py.events.shop.orders.v1
routing key: order-created.v1
```

The service contract version chooses the source exchange. The event schema
version chooses a specific payload contract on that exchange. Keep both
explicit while old and new contracts coexist.

## Publish Through EventDispatcher

When `MicroservicesModule.for_root()` uses a keyed transport reference such as
`RabbitMqTransport`, it registers and exports one lifecycle-managed
`EventDispatcher`. The dispatcher derives source identity and routing from that
root, so application code cannot spoof a source, exchange, destination,
subscription, or message ID.

```python
from uuid import UUID

import msgspec
from tori_py_microservices import EventDispatcher


class OrderCreated(msgspec.Struct, frozen=True):
    event_id: UUID
    order_id: int
    total_cents: int


class OrderEvents:
    def __init__(self, events: EventDispatcher) -> None:
        self._events = events

    async def order_created(self, event: OrderCreated) -> None:
        receipt = await self._events.publish(
            "order-created",
            1,
            event,
            headers={"traceparent": "validated-application-value"},
            correlation_id=event.event_id,
            require_route=True,
        )
        assert receipt.routed
```

`publish()` accepts optional safe headers, correlation/causation IDs, and an
explicit UTC `occurred_at`. Supplying `occurred_at` is useful when an outbox
relay must preserve the time at which the application fact originally occurred.
The dispatcher generates a new transport message ID for each publication.

Zero subscribers is valid by default. In that case a confirmed mandatory
publication is returned as `PublicationReceipt(routed=False)`. Use
`require_route=True` when the application requires at least one binding; it
raises `TransportUnroutableError` if none exists. Neither `routed=True` nor a
publisher confirm proves that a consumer is online or that a handler ran.

Publication is accepted only while the dispatcher transport is running. During
quiescence it closes admission first and drains accepted publication tasks
against the shared shutdown deadline.

## Declare A Consumer

Event handlers are explicit controller methods and return `None`:

```python
from typing import Annotated

from tori_py import controller
from tori_py_microservices import (
    Context,
    EventContext,
    EventDispatchMode,
    Header,
    Payload,
    ServiceIdentity,
    event_handler,
)

ORDERS = ServiceIdentity("shop", "orders", 1)


@controller()
class NotificationsController:
    @event_handler(
        ORDERS,
        "order-created",
        schema_version=1,
        mode=EventDispatchMode.SERVICE_POOL,
        subscription="notification-workers",
    )
    async def order_created(
        self,
        event: Annotated[OrderCreated, Payload()],
        outbox_id: Annotated[str, Header("outbox_event_id")],
        context: Annotated[EventContext, Context()],
    ) -> None:
        del event, outbox_id, context
```

Handlers use the same payload, context, headers, provider injection, guards,
pipes, interceptors, filters, and exact-owner work scopes as RPC. Every delivery
attempt gets a fresh scope. ACK eligibility begins only after the pipeline and
scope cleanup succeed.

The `subscription` is an application contract and part of the queue name. Keep
it stable across deployments for reliable handlers. Python class and method
names do not determine queue identity. Two distinct subscriptions to the same
event produce two queues and each receives the event independently; one
handler's failure does not force the other to repeat.

## Delivery Modes And Cardinality

The mode belongs to `@event_handler`, never to `EventDispatcher`.

| Mode | Queue ownership | Delivery cardinality | Offline behavior |
| --- | --- | --- | --- |
| `SERVICE_POOL` | One durable queue per destination service, event, schema, and subscription | One replica in that destination pool receives each attempt | Backlog is retained |
| `SINGLETON` | One durable global queue per source event/schema and subscription | One declaring consumer receives each attempt globally | Backlog is retained |
| `BROADCAST`, `reliable=False` | One exclusive auto-delete queue per live destination instance | Every live instance receives its own copy | Offline instances miss events |
| `BROADCAST`, `reliable=True` | One durable queue per stable destination instance | Every declared stable instance receives its own copy | Backlog is retained within queue TTL/expiry policy |

### Service Pool

All replicas with the same destination service identity and subscription consume
one queue. Scaling replicas changes capacity, not cardinality. One replica gets
each delivery attempt, with no strict round-robin guarantee.

Use separate subscription names for independent logical effects, even when two
handlers consume the same payload.

### Singleton

Every application declaring the same source event, schema, and singleton
subscription competes on one global queue, even across destination service
identities. This is one delivery attempt to one consumer. It is not leader
election, a distributed lock, or exclusive ownership outside that message.

Reusing a singleton subscription for incompatible effects or payload meanings is
a deployment contract violation.

### Broadcast

Ephemeral broadcast is the default broadcast policy. Its generated instance
identity and exclusive auto-delete queue are appropriate for cache invalidation,
local wakeups, and presence-like facts that may be lost while offline.

Reliable broadcast requires an explicit stable instance identity:

```python
from tori_py_microservices import MicroservicesOptions

options = MicroservicesOptions(instance_id="cache-consumer-1")
```

Pass `options` to the destination service's `MicroservicesModule.for_root()` and
declare `reliable=True` on the handler. RabbitMQ uses a durable classic queue and
an exclusive consumer, so a duplicate live instance identity fails instead of
silently sharing deliveries. Operators own stable identity allocation, orphan
queue cleanup, retention, and queue-count growth. Large replayable fan-out is a
stream/log use case, not this mode.

`SERVICE_POOL` and `SINGLETON` are always reliable and reject an explicit
`reliable` argument. Broadcast defaults to `False` when omitted.

## Failure And Retry

Default invocation classification is:

| Failure | Settlement direction |
| --- | --- |
| Successful handler and scope cleanup | ACK |
| Malformed envelope, unsupported schema, invalid typed input, authorization/configuration failure, or `MessageRejectedError` | Terminal reject |
| `MessageRetryableError` | Bounded retry for reliable subscriptions |
| Unexpected ordinary event-handler exception | Bounded retry for reliable subscriptions |
| Cancellation, process/connection loss, or scope-finalization uncertainty | Leave unsettled so broker recovery can redeliver |

RabbitMQ retry does not sleep while holding the original delivery. It publishes
the same transport message identity and a broker-visible attempt count to a
bounded delayed retry queue, awaits confirmation, then ACKs the original. The
retry queue dead-letters back after its delay. At the attempt limit, the primary
delivery is rejected into its dead-letter path. Ephemeral broadcast has no
durable retry/DLX topology.

A filter can intentionally convert an event exception to success, which permits
ACK. Treat that as explicit application policy and test it.

## At Least Once And Deduplication

Publisher confirms and consumer ACKs are separate. A connection can fail after
a handler commits but before its ACK reaches RabbitMQ, so the same event can be
handled again. Framework message IDs are stable across broker redelivery but do
not define application deduplication scope.

For durable effects, use an application event ID and a consumer-owned inbox or
unique record. In one local transaction:

1. Insert/check `(consumer, application_event_id)` under a unique constraint.
2. Apply the local effect only when the record is new.
3. Commit both together.
4. Return successfully so the framework can ACK.

An outbox relay may also publish the same application event more than once. Keep
the application event ID stable even though separate `EventDispatcher.publish()`
calls receive new transport message IDs. The multi-process example demonstrates
an orders outbox and notification deduplication; see
[Operations](operations.md#outbox-and-inbox-boundary).
