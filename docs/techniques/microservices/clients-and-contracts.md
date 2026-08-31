# Clients And Contracts

`ServiceCluster` is one asynchronous, bounded RPC client runtime shared across
many target services. Typed service contracts layer application-owned Protocols
and DTOs over that runtime without changing transport guarantees.

## Prefer Typed Protocol Contracts

Define transport DTOs with `msgspec.Struct`, then map a `Protocol` to one complete
service identity:

```python
from collections.abc import Mapping
from typing import Annotated, Protocol
from uuid import UUID

import msgspec
from tori_py_microservices import (
    CallHeaders,
    CallTimeout,
    CausationId,
    CorrelationId,
    ServiceIdentity,
    rpc_call,
    service_contract,
)

CATALOG = ServiceIdentity("shop", "catalog", 1)


class GetItem(msgspec.Struct, forbid_unknown_fields=True):
    item_id: int


class Item(msgspec.Struct, frozen=True):
    item_id: int
    name: str


@service_contract(CATALOG)
class CatalogService(Protocol):
    @rpc_call("get-item", payload=GetItem)
    async def get_item(
        self,
        item_id: int,
        *,
        correlation_id: Annotated[UUID | None, CorrelationId()] = None,
        causation_id: Annotated[UUID | None, CausationId()] = None,
        headers: Annotated[Mapping[str, object] | None, CallHeaders()] = None,
        timeout: Annotated[float | None, CallTimeout()] = None,
    ) -> Item: ...
```

Contract compilation enforces:

- the decorated class is a `Protocol`;
- every public method is async and has `@rpc_call` metadata;
- aliases/schema versions are valid and not duplicated;
- the payload is an explicit `msgspec.Struct` type;
- normal method parameters exactly match DTO field names and order;
- envelope metadata parameters are keyword-only and use at most one marker;
- every method has a non-`None` response annotation;
- inherited contract methods cannot be reused across service identities.

The framework does not infer or generate distributed schemas from signatures.
The DTO is the explicit wire payload contract; the Protocol is the caller-facing
API.

`CorrelationId`, `CausationId`, `CallHeaders`, and `CallTimeout` values are placed
in envelope metadata and do not become DTO fields. A positive finite
`timeout=` on `@rpc_call` supplies a method default only when the Protocol method
does not declare a `CallTimeout` parameter. Current timeout precedence is:

1. A non-`None` value passed through a `CallTimeout` parameter.
2. If a `CallTimeout` parameter exists but resolves to `None`, the cluster's
   `default_rpc_timeout`; the decorator timeout is not consulted.
3. If there is no `CallTimeout` parameter, the `@rpc_call(timeout=...)` value.
4. Otherwise, the cluster's `default_rpc_timeout`.

Do not combine a nullable `CallTimeout` parameter with a decorator timeout when
the decorator value must be the omitted-call default. All selected values remain
bounded by the cluster maximum.

## Share The Contract With The Server

Reference the Protocol method from `@rpc` to reuse identity and verify both sides
at startup:

```python
from typing import Annotated

from tori_py import controller
from tori_py_microservices import Payload, rpc


@controller()
class CatalogController:
    @rpc(CatalogService.get_item)
    async def get_item(
        self,
        payload: Annotated[GetItem, Payload()],
    ) -> Item:
        return Item(payload.item_id, "Keyboard")
```

The handler must bind exactly one complete `Payload()` of the declared DTO and
return the declared response type. The runtime also rejects a contract method
whose service identity differs from the application's microservices root.

Sharing a small contract package does not mean sharing ORM models, CQRS commands,
repositories, or domain objects. Keep those local and translate at the service
boundary.

## Register Proxies With DI

Register one RabbitMQ root and one client cluster. Each contract is exported as
its Protocol token:

```python
from tori_py import module
from tori_py_microservices import (
    ClientsModule,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    ServiceClusterOptions,
)

rabbitmq = RabbitMqModule.for_root(
    RabbitMqOptions("amqp://gateway:password@rabbitmq/gateway")
)
clients = ClientsModule.register_cluster(
    RabbitMqTransport(),
    imports=(rabbitmq,),
    contracts=(CatalogService,),
    options=ServiceClusterOptions(
        default_rpc_timeout=3.0,
        max_rpc_timeout=10.0,
        max_pending_requests=512,
    ),
)


@module(imports=(clients,))
class GatewayModule:
    pass
```

Normal constructor injection is then narrow and statically meaningful:

```python
class CatalogGateway:
    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    async def get_item(self, item_id: int) -> Item:
        return await self._catalog.get_item(item_id, timeout=2.0)
```

The implementation is one generic dynamic proxy. `__getattr__` exposes only
precompiled contract methods, caches their async callables, binds Python
arguments, converts them to the declared DTO, and delegates to an immutable
`ServiceProxy`. It does not synthesize arbitrary remote method names.

The default cluster also exports `ServiceCluster`. Named clusters export the
deterministic token returned by `ClientsModule.get_cluster_token(key)` rather
than an ambiguous unqualified cluster alias. A client-only HTTP gateway does not
need `MicroservicesModule` or a service identity of its own.

## Low-Level ServiceProxy

Use the explicit transport-level API when a Protocol is not appropriate:

```python
from tori_py_microservices import ServiceCluster, ServiceIdentity

catalog = cluster.service(ServiceIdentity("shop", "catalog", 1))
item = await catalog.request(
    "get-item",
    {"item_id": 42},
    response_type=Item,
    schema_version=1,
    timeout=2.0,
)
```

If `ServiceClusterOptions.default_namespace` is configured,
`cluster.service("catalog", version=1)` is available. `cluster["catalog"]`
additionally requires `default_contract_version`. Prefer complete identities in
shared infrastructure and diagnostics.

One cluster owns:

- one `ClientTransport` and status stream;
- one RabbitMQ reply route/consumer when RPC is enabled;
- one bounded pending-correlation map across all target services;
- one bounded LRU cache of immutable service proxies;
- one close operation.

`ClientsModule`-created RabbitMQ clusters own their client transport and close it
with the application. A manually constructed `ServiceCluster` defaults to
`manage_transport=False`; the caller then owns transport shutdown.

## Deadline And Correlation Policy

`ServiceClusterOptions` defaults to a 5-second call timeout, 30-second maximum,
1,024 pending requests, and 1,024 cached proxies. Configure explicit bounds for
the deployment rather than treating these as throughput targets.

The pending entry is registered before publication, so an immediate reply can
win a race with a still-pending publisher confirm. A supplied correlation ID
must not already be pending or completed on that transport. Usually let the
cluster generate it; use application IDs in the DTO for idempotency.

One deadline covers readiness, publication, confirm, and reply wait. A timed-out
or cancelled pending entry is removed, but that does not prove the remote
handler did not run. Unknown, late, duplicate, and cancelled replies are ACKed
and discarded; they never recreate a waiter.

After reply transport loss, all calls associated with the old route fail with
`RpcOutcomeUnknownError`. The RabbitMQ client creates and consumes a fresh reply
route before admitting new calls. It never republishes old requests.

## Handle Failures At The Boundary

Catch the narrow outcomes that your boundary can translate meaningfully:

```python
from tori_py_microservices import (
    RemoteRpcError,
    RpcOutcomeUnknownError,
    RpcProtocolError,
    RpcTimeoutError,
    UnknownServiceError,
)

try:
    item = await catalog.get_item(42)
except RemoteRpcError as error:
    # Map stable application codes such as not_found or conflict.
    raise
except UnknownServiceError:
    # No route existed for the target service/version.
    raise
except RpcTimeoutError:
    # Local deadline elapsed; remote completion may still be possible.
    raise
except RpcOutcomeUnknownError:
    # Reconcile by application identity before deciding whether to retry.
    raise
except RpcProtocolError:
    # Contract/peer defect, not a transient business outcome.
    raise
```

Do not implement a blanket proxy retry. `RemoteRpcError.retryable` is advisory,
not an instruction to resend. For commands with side effects, a retry policy
needs a stable application idempotency key, a persistent server-side decision,
and a way to return/reconcile the original result.

## Evolve Contracts Deliberately

- One service root may register only one handler for an RPC method alias,
  regardless of `schema_version`. Two handlers such as `("get-item", 1)` and
  `("get-item", 2)` cannot coexist in one application.
- Increment `schema_version` only for a coordinated cutover in which all callers
  and the one deployed handler move together. A mismatched caller receives
  `unsupported_schema`.
- When old and new callers must overlap, use a new stable method alias such as
  `get-item-v2`, or deploy a new `ServiceIdentity.contract_version` and retain
  the old service version until its callers are gone.
- Increment `ServiceIdentity.contract_version` when the service contract as a
  whole requires an incompatible routing boundary.
- Add new methods with new aliases; never silently retarget an old alias.
- Keep old DTO handlers on their old alias or old service identity while old
  callers remain deployed; do not attempt two schema handlers under one alias.
- Treat response-type decode failures as `RpcProtocolError`, not as fallback to
  untyped data.
- Keep integration DTO packages narrow and dependency-light.

Typed contracts improve startup validation and call-site typing. They do not add
service discovery, retries, cancellation, exactly-once execution, or schema
negotiation.
