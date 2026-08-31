# Microservices

ToriPy's optional microservices package adds asynchronous RPC, one-way events,
typed client contracts, and pluggable transports to ordinary ToriPy
applications. It does not split a process into independently deployable
services, provide service discovery, or remove distributed-systems failure
modes. Choose deployment boundaries first, then use this package at those
boundaries.

## Install

The transport-neutral package includes the handler compiler, invocation
pipeline, client cluster, event dispatcher, and in-memory transport:

```text
uv add tori-py-microservices
```

Add the optional RabbitMQ adapter only where it is used:

```text
uv add "tori-py-microservices[rabbitmq]"
```

Importing `tori_py_microservices` does not import `aio_pika`, open a socket, or
declare broker resources. RabbitMQ is loaded when its managed transport starts.

## Core Model

One ToriPy application has at most one `MicroservicesModule` root and therefore
at most one logical service identity:

```python
from tori_py_microservices import ServiceIdentity

CATALOG = ServiceIdentity("shop", "catalog", 1)
```

The three identity components are part of the public contract:

| Component | Example | Meaning |
| --- | --- | --- |
| Namespace | `shop` | Stable organizational routing boundary |
| Service name | `catalog` | Logical service, shared by all its replicas |
| Contract version | `1` | Incompatible service contract generation |

Namespace, service, RPC method, event, subscription, and configured instance
aliases match `[a-z][a-z0-9_-]{0,62}`. Versions are positive integers. Do not
derive these values from Python class/module names or deployment-generated pod
names.

The normalized service label is `shop.catalog.v1`. RabbitMQ uses it to derive:

```text
RPC queue:   tori_py.rpc.shop.catalog.v1
RPC binding: shop.catalog.v1.*
RPC call:    shop.catalog.v1.get-item
```

All methods of one service share one queue. Replicas with the same complete
identity are equal competing consumers on that queue. A different contract
version is a different queue and compatibility boundary.

## Compose A Service

Controllers remain ordinary, explicitly registered ToriPy controllers. The
microservices root discovers all of them after the application graph is
compiled; there is no endpoint module, package scan, or process-global handler
registry.

```python
from typing import Annotated

import msgspec
from tori_py import controller, module
from tori_py_microservices import (
    MicroservicesModule,
    Payload,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    ServiceIdentity,
    rpc,
)

CATALOG = ServiceIdentity("shop", "catalog", 1)


class GetItem(msgspec.Struct, forbid_unknown_fields=True):
    item_id: int


class Item(msgspec.Struct, frozen=True):
    item_id: int
    name: str


@controller()
class CatalogController:
    @rpc("get-item")
    async def get_item(
        self,
        payload: Annotated[GetItem, Payload()],
    ) -> Item:
        return Item(payload.item_id, "Keyboard")


rabbitmq = RabbitMqModule.for_root(
    RabbitMqOptions("amqp://catalog:password@rabbitmq/catalog")
)
microservices = MicroservicesModule.for_root(
    CATALOG,
    transport=RabbitMqTransport(),
    imports=(rabbitmq,),
)


@module(imports=(microservices,), controllers=(CatalogController,))
class CatalogApplication:
    pass
```

Use `amqps://` and `tls=True` outside a trusted local development environment;
the plain AMQP URL above is only a composition example. See
[RabbitMQ](rabbitmq.md) for secure configuration.

`MicroservicesModule` is a lifecycle-managed capability, not an application
adapter. A broker-only service can use ToriPy's default/no-op adapter. A hybrid
application can use `StarletteAdapter` while the same lifecycle also starts RPC
and event consumers. HTTP routes and message routes remain separate concerns.

## Responsibility Boundaries

The package owns:

- stable envelopes, JSON encoding, limits, and typed transport errors;
- controller discovery, binding, pipeline execution, and one work scope per
  delivery attempt;
- finite RPC deadlines, reply correlation, and bounded client state;
- explicit event subscription topology and delivery settlement;
- transport lifecycle, readiness states, recovery, and bounded shutdown.

The application owns:

- authentication, authorization, and business policy;
- request idempotency and event deduplication identities;
- database transactions and consistency between state and messages;
- outbox, inbox, reconciliation, retention, replay, sagas, and workflows;
- deployment topology, credentials, broker policies, and operational alerts;
- translation between integration DTOs and local CQRS/domain messages.

RPC and durable event handling are at least once. Publisher confirmation means
broker acceptance, not handler execution or transactional coupling to a local
database. Exactly-once execution and remote cancellation are not provided.

## Technique Guide

- [RPC](rpc.md): service routes, handlers, binding, pipelines, scopes,
  deadlines, responses, and uncertain outcomes.
- [Events](events.md): `EventDispatcher`, subscription modes, cardinality,
  reliability, retry, and deduplication.
- [Clients And Contracts](clients-and-contracts.md): `ServiceCluster`, typed
  Protocol proxies, DTO evolution, metadata, and client error policy.
- [Transports](transports.md): transport-neutral contracts, lifecycle, custom
  adapters, and in-memory composition.
- [RabbitMQ](rabbitmq.md): module wiring, exact topology, TLS, confirms,
  reconnect, retry/DLX, readiness, and shutdown.
- [Operations](operations.md): production checks, monitoring, runbooks,
  idempotency, outbox/inbox, and the multi-process example.

## Executable Examples

The focused examples cover standalone RPC, competing in-memory replicas, hybrid
HTTP/RPC hosting, all event modes, deadlines, and the outbox boundary:

- `examples/tori_py/microservices/rpc_service.py`
- `examples/tori_py/microservices/replicas.py`
- `examples/tori_py/microservices/events.py`
- `examples/tori_py/microservices/policies.py`

```text
uv run pytest examples/tori_py/microservices -q
```

The application example has four independent processes: an HTTP gateway,
catalog, orders, and notifications. Each service owns its database; the orders
service owns an outbox and notifications performs durable event deduplication.
See the
[`examples/tori_py/microservices_app`](https://github.com/mikeoz32/tori-py/tree/main/examples/tori_py/microservices_app)
application.
