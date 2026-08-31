# Transports

The base package separates message semantics from broker mechanics. Handler
discovery, DI, work scopes, pipelines, envelopes, codecs, deadlines, and result
classification remain transport-neutral. An adapter owns encoded publication,
delivery, settlement, native resources, and lifecycle status.

## Public Contracts

The main boundaries are structural runtime-checkable Protocols:

| Contract | Responsibility |
| --- | --- |
| `ServerTransportFactory` | Create one unopened server transport for a service identity and options |
| `ServerTransport` | Prepare routes, start intake, publish replies, settle deliveries, stop intake, close, and report status |
| `ClientTransportFactory` | Create one unopened outbound transport |
| `ClientTransport` | Publish RPC/events, stream correlated replies, close, and report status/generation |
| `KeyedTransportFactoryReference` | Refer to exact adapter-owned server/client factories from ToriPy modules |

The data contracts include `Publication`, `PublicationReceipt`,
`EncodedDelivery`, `EventSubscription`, `ReplyProtocolFailure`,
`TransportStatus`, and `TransportStatusEvent`.

`PublicationReceipt` represents transport/broker acceptance. Its `routed` field
does not assert consumer presence or execution. `EncodedDelivery` contains safe,
immutable broker facts and an opaque read-only native value; it does not expose
public settlement functions to handlers.

## Lifecycle

A server follows this state progression:

```text
CREATED -> PREPARED -> RUNNING -> QUIESCING -> CLOSED
```

`prepare()` declares/validates routes while intake is closed. `start()` installs
one dispatcher callback and becomes ready only after consumers are active.
`stop_intake()` closes admission before accepted work drains. `close()` releases
adapter resources and is idempotent.

A client begins at `CREATED`, starts to `RUNNING`, may move through
`QUIESCING` during recovery, and ends at `CLOSED`. Status events include a
connection generation so reply routers and settlement adapters can fence stale
state.

The transport must not:

- inspect controller decorators or discover providers;
- execute ToriPy guards, pipes, interceptors, filters, or work scopes;
- convert an indeterminate operation into success;
- detach unowned handler/settlement tasks;
- settle an old delivery tag on a replacement channel;
- claim universal ordering, durability, or balancing semantics.

## In-Memory Composition

`InMemoryBroker`, `InMemoryServerTransport`, and `InMemoryClientTransport` model
bounded queues, explicit routing, competing consumers, reply correlation, manual
settlement, redelivery, and all event modes in one process.

For a normal ToriPy service test, supply a small structural server factory and a
direct client transport:

```python
from tori_py_microservices import (
    ClientsModule,
    InMemoryBroker,
    InMemoryClientTransport,
    InMemoryServerTransport,
    MicroservicesModule,
    MicroservicesOptions,
    ServiceIdentity,
)


class InMemoryServerFactory:
    def __init__(self, broker: InMemoryBroker) -> None:
        self._broker = broker

    def create(
        self,
        identity: ServiceIdentity,
        options: MicroservicesOptions,
    ) -> InMemoryServerTransport:
        return InMemoryServerTransport(
            self._broker,
            identity,
            prefetch=options.max_inflight_deliveries,
        )


broker = InMemoryBroker(
    max_queue_messages=1_000,
    max_delivery_attempts=3,
)
service = MicroservicesModule.for_root(
    ServiceIdentity("tests", "catalog", 1),
    transport=InMemoryServerFactory(broker),
)
clients = ClientsModule.register_cluster(InMemoryClientTransport(broker))
```

Import `service` into the service application module and `clients` where an RPC
client is required. Close the shared broker in test teardown after applications
and manually owned clients stop.

A direct server factory provides only the inbound factory contract, so
`MicroservicesModule` does not export `EventDispatcher`. For event-publisher
composition tests, either construct `EventDispatcher` with a small
`ClientTransportFactory` and manage its lifecycle explicitly, or provide a test
adapter implementing `KeyedTransportFactoryReference` with both factories.
Production RabbitMQ composition already provides both.

The low-level in-memory transports are also useful for adapter/cluster tests that
manually call `prepare()`, `start()`, and `ServiceCluster`. That style bypasses
controller discovery and the message pipeline, so use application composition
when testing handlers, DI scopes, or lifecycle.

## In-Memory Is Not RabbitMQ

| Property | In-memory | RabbitMQ |
| --- | --- | --- |
| Process boundary | One event loop/process | Network broker and independent processes |
| Persistence | None | Durable queues/messages according to topology and broker configuration |
| Broker restart/recovery | Not modeled | Framework-coordinated topology and consumer recovery |
| Publisher confirms/returns | Deterministic acceptance model | Native confirms, mandatory returns, and indeterminate network outcomes |
| TLS/permissions | Not applicable | Deployment requirement |
| Queue policy behavior | Simplified bounded model | RabbitMQ quorum/classic queue, TTL, retry, and DLX behavior |

Use in-memory tests for deterministic handler and contract behavior. Use real
RabbitMQ tests for topology equivalence, reconnect, redelivery, publisher
confirmation, mandatory returns, queue retention, and shutdown races.

## Settlement Contract

The runtime returns one `SettlementRecommendation` after an invocation attempt:

| Recommendation | Adapter meaning |
| --- | --- |
| `ACK` | Remove the delivery after all required response/effect conditions are definitive |
| `RETRY` | Follow the adapter's bounded retry policy |
| `REJECT` | Terminally reject without immediate requeue |
| `UNSETTLED` | Outcome is unsafe to settle; fence/close as needed and allow broker redelivery |

Settlement is private to the adapter. Calling it twice is a
`DuplicateSettlementError`. On RabbitMQ, ACK/NACK uncertainty fences the
connection; an old generation is never treated as successfully settled.

## Implementing Another Adapter

A custom adapter must preserve the transport contract while documenting native
differences. At minimum:

1. Create no network resources from imports, module descriptor materialization,
   or factory `create()`.
2. Bound queueing, pending replies, callbacks, concurrency, reconnect, and
   shutdown.
3. Validate publication routing/correlation before native I/O.
4. Register pending correlation before a reply can arrive.
5. Distinguish rejected, unroutable, timed-out, unavailable, and indeterminate
   publications with typed errors.
6. Transfer each accepted delivery to an owned task without detaching callback
   work.
7. Settle only after the runtime completion and scope-cleanup boundary.
8. Preserve at-least-once behavior and stable transport message identity across
   redelivery where the broker supports it.
9. Stop intake, cross any callback scheduling fence, drain accepted work, then
   close native resources.
10. Emit distinct bounded status transitions and fence stale generations.
11. State ordering, durability, routing, delivery, and failover guarantees
    without borrowing RabbitMQ claims.

The package's shared conformance suite exercises routing, response-before-
settlement, retries, terminal rejection, bounded inflight delivery, unsettled
redelivery, intake drain, and idempotent close. Run the current reference tests:

```text
uv run pytest packages/tori-py-microservices/tests/test_transport_conformance.py -q
uv run pytest packages/tori-py-microservices/tests/test_inmemory.py -q
```
