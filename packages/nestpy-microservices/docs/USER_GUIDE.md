# Nestpy Microservices User Guide

## Installation

The base package provides the transport-neutral RPC, event, compiler, and
in-memory APIs:

```text
uv add nestpy-microservices
```

Install RabbitMQ support only for applications that use the broker adapter:

```text
uv add "nestpy-microservices[rabbitmq]"
```

Importing `nestpy_microservices` or its RabbitMQ facade does not import
`aio_pika` or connect to a broker. The RabbitMQ dependency is loaded when a
RabbitMQ transport is started.

## Service Identity

Every application-facing service has one `ServiceIdentity` consisting of a
namespace, service name, and contract version. One application may configure
at most one `MicroservicesModule` root. Multiple controllers belong to that
root and are discovered at startup.

```python
from nestpy_microservices import (
    MicroservicesModule,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    ServiceIdentity,
)

SERVICE = ServiceIdentity("catalog", "catalog-api", 1)
rabbitmq = RabbitMqModule.for_root(
    RabbitMqOptions("amqp://catalog:password@rabbitmq/catalog")
)
root = MicroservicesModule.for_root(
    SERVICE,
    transport=RabbitMqTransport(),
    imports=(rabbitmq,),
)
```

The application owns authentication, authorization, persistence, idempotency,
and business policy. The transport does not infer these policies.

## RPC Controllers

Decorate direct controller methods with `@rpc`. The compiler rejects duplicate
aliases, unsupported middleware, variadic message parameters, and invalid
context or payload markers.

```python
from typing import Annotated

from nestpy import Context, controller
from nestpy_microservices import Payload, RpcContext, rpc


@controller()
class CatalogController:
    @rpc("lookup")
    async def lookup(
        self,
        payload: Annotated[dict[str, str], Payload()],
        context: Annotated[RpcContext, Context()],
    ) -> dict[str, object]:
        return {"sku": payload["sku"], "request_id": context.request_id}
```

The controller is compiled through discovery; endpoint modules and package
scanning are not required.

## RabbitMQ Topology

For one logical service, the adapter declares one RPC exchange, one durable
service queue, and one wildcard topic binding matching
`<namespace>.<service>.v<version>.*`. RPC methods use distinct routing keys but
do not receive separate queues. Replicas consume the same service queue.

The client owns one reply route and one reply consumer for a `ServiceCluster`.
The correlation ID selects the pending request. A reply can win a race with a
still-pending publisher confirm; a connection loss before a definitive
publication result is indeterminate and is never automatically republished.

Competing consumers balance work without a strict round-robin guarantee.
Prefetch, concurrency, pending replies, and queues are bounded by options.

## RPC Deadlines And Delivery Identity

RPC calls have a finite timeout. The client sends an absolute UTC deadline and
uses one monotonic budget for connection wait, publication, and reply wait. A
request can time out before write, after accepted publication, or with an
indeterminate publication outcome; these are different failures.

The transport does not retry accepted or indeterminate RPC calls. Its
`message_id` identifies one delivery and remains stable across broker
redelivery; it is not an application idempotency key. If a use case needs
deduplication, define the identity, scope, and persistence policy in that
application's request contract and storage.

Caller cancellation is local; it does not cancel work already accepted by the
service. If cancellation leaves publication or settlement uncertain, the
client fences the connection and reports an indeterminate outcome. A service
may execute a request more than once, and a client may observe duplicate or
late replies; replies with no pending correlation are acknowledged and ignored.

## Typed Service Contracts

Use a `Protocol` to declare the application-facing client API and let one
dynamic proxy bind normal Python calls to explicit RPC DTOs:

```python
@service_contract(CATALOG)
class CatalogService(Protocol):
    @rpc_call("get-item", payload=GetCatalogItem)
    async def get_item(self, item_id: int) -> CatalogItem: ...
```

Register contracts with `ClientsModule.register_cluster(...,
contracts=(CatalogService,))` and inject `CatalogService`. The proxy uses
`__getattr__` only for methods precompiled from the contract. Keep envelope
metadata out of payloads with keyword-only `Annotated` markers, for example
`headers: Annotated[Mapping[str, object], CallHeaders()]`.

Use `@rpc(CatalogService.get_item)` on the server to share the alias and schema
version. Startup validates that the handler's complete `Payload()` DTO and
return annotation match the Protocol method. DTOs remain explicit; Protocol
parameters are mapped by name and must exactly match the declared DTO fields.

## Events

`EventDispatchMode.SERVICE_POOL` provides competing service consumers.
`SINGLETON` creates one durable global subscription queue; all consumers
declaring that subscription compete for delivery attempts, so it is not leader
election. `BROADCAST` creates a queue per destination instance. `reliable=True`
requires an explicit stable `MicroservicesOptions.instance_id`, durable queue,
exclusive consumer, and operator-managed orphan cleanup. `reliable=False` is
ephemeral and can lose events while offline. Durable queue semantics described
here are RabbitMQ-specific; the in-memory transport is a test transport.

Publisher confirms and consumer acknowledgements are separate. A confirmed
publication is not a transaction with a handler side effect.

## Hybrid Hosting And Testing

An application can expose HTTP controllers and RPC/event controllers from the
same Nestpy application, while keeping HTTP routing and message routing as
separate transport concerns. Use the in-memory broker for deterministic unit
and contract tests, and Docker-backed RabbitMQ tests for topology, recovery,
redelivery, and confirmation behavior.

See the executable examples in
[`examples/nestpy/microservices`](../../../examples/nestpy/microservices/README.md).
The application-level
[`microservices_app`](../../../examples/nestpy/microservices_app/README.md)
adds an HTTP gateway, three database-owning services, local CQRS, an outbox
relay, and a runnable Docker Compose stack.
