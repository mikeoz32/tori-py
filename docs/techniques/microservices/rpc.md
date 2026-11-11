# RPC

ToriPy RPC is finite-deadline request/response messaging over a logical service
cluster. It is suitable when the caller needs a typed response and explicitly
accepts timeout, duplicate execution, and outcome uncertainty.

## Identity And Routing

An RPC target consists of a complete `ServiceIdentity`, a stable method alias,
and a positive payload schema version. For this target:

```python
from tori_py_microservices import RpcTarget, ServiceIdentity

target = RpcTarget(
    ServiceIdentity("shop", "catalog", 1),
    "get-item",
    1,
)
```

the RabbitMQ routing key is `shop.catalog.v1.get-item`. The schema version is in
the request envelope, not the routing key. Service and contract versions choose
the queue; the method chooses local dispatch after RabbitMQ routes through the
single `shop.catalog.v1.*` binding.

This distinction produces useful failure behavior:

| Condition | Result |
| --- | --- |
| Unknown service or contract version | Mandatory publication is unroutable; the client raises `UnknownServiceError` |
| Known service, unknown method | Service returns sanitized `method_not_found` |
| Known method, unsupported schema | Service returns sanitized `unsupported_schema` |
| Durable queue exists but has no consumers | Publication can be routed; the call ends by its deadline |

Routing success is not service membership or proof of a live replica.

## Declare A Handler

`@rpc` stores direct method metadata. The controller must still be registered in
a ToriPy module.

```python
from collections.abc import Mapping
from typing import Annotated

import msgspec
from tori_py import Inject, controller
from tori_py_microservices import (
    Context,
    Header,
    Headers,
    Payload,
    RpcContext,
    rpc,
)


class QuoteRequest(msgspec.Struct, forbid_unknown_fields=True):
    sku: str
    quantity: int


class Quote(msgspec.Struct, frozen=True):
    sku: str
    total_cents: int


@controller()
class PricingController:
    @rpc("quote", schema_version=1)
    async def quote(
        self,
        request: Annotated[QuoteRequest, Payload()],
        context: Annotated[RpcContext, Context()],
        headers: Annotated[Mapping[str, object], Headers()],
        pricing: Annotated[object, Inject("pricing")],
        trace_id: Annotated[str | None, Header("trace_id")] = None,
    ) -> Quote:
        del context, headers, trace_id, pricing
        return Quote(request.sku, request.quantity * 500)
```

The injected example provider would normally have a concrete protocol/type
instead of `object`; it is abbreviated only to show the marker. Register the
`"pricing"` token in a module visible to this controller.

Handler rules are validated before intake opens:

- handlers are `async` and declare a return annotation;
- aliases are unique across every controller in the application;
- only methods declared directly on the controller class are discovered;
- every non-`self` parameter has exactly one supported `Annotated` marker;
- positional-only, `*args`, and `**kwargs` parameters are rejected;
- at most one parameter binds the complete payload;
- the context annotation accepts `RpcContext`;
- typed payload, payload-field, and header values are converted with `msgspec`;
- the returned value is validated against the return annotation before encoding.

The available bindings are:

| Marker | Value |
| --- | --- |
| `Payload()` | Complete payload converted to the annotation |
| `Payload("field")` | One named payload field |
| `Context()` | Immutable `RpcContext` |
| `Headers()` | Complete immutable safe header mapping |
| `Header("name")` | One named safe header |
| `Inject(token)` | Provider resolved with the handler owner's module visibility |

Missing optional payload/header fields can use Python defaults. Invalid typed
input is rejected before a work scope opens, avoiding transactional or other
request-scoped resource acquisition for malformed messages.

## Pipeline And Scope

Message handlers reuse ToriPy guards, pipes, interceptors, filters, and their
normal metadata decorators. HTTP middleware is not a message pipeline and
message middleware declarations are rejected.

The effective order is:

```text
filter boundary(
  global -> controller -> method guards
  bind prepared values, context, and injected providers
  global -> controller -> method pipes, per bound argument
  global -> controller -> method interceptors
  handler
  result validation and encoding
)
```

Interceptors unwind in reverse order and each `next` callback is one-shot.
Filters catch ordinary exceptions, not cancellation/process-control values. A
message interceptor or filter cannot return a native HTTP response.

Every delivery attempt opens a fresh exact-owner ToriPy work scope. Request
providers are cached within that attempt; transient providers and cleanup belong
to it. The controller itself remains a singleton, so do not keep per-message
mutable state on controller attributes.

Settlement occurs after interceptors finish and the work scope closes. Scope
finalization failure overrides a provisional result and leaves the request
unsettled because durable effects may be uncertain. `RpcContext` exposes stable
message/correlation/causation IDs, attempt/redelivery facts, immutable metadata,
the scoped resolver, and read-only native metadata through `unwrap()`. It does
not expose ACK/NACK or channel mutation.

## Write Pipeline Components

Message components implement the same protocols as HTTP components and receive
an `RpcContext` or `EventContext` as their `ExecutionContext`:

| Context member | Value |
| --- | --- |
| `execution_kind` | `"rpc"` or `"event"` |
| `route_id` | `ControllerClass.method` of the handler |
| `message_id`, `correlation_id`, `causation_id` | Message identities |
| `attempt`, `redelivered` | Delivery attempt facts |
| `received_at`, `expires_at` | UTC timestamps |
| `metadata` | `routing_key` and `kind` of the delivery |
| `resolver` | The delivery's work-scope resolver |
| `unwrap()` | The transport's native value, read-only |

Application headers are not in `metadata`. Bind them in the handler with
`Header("name")` or `Headers()`; pipes then see them as arguments.

### Guards

A guard returns `False` to deny the message. Denial raises
`MessageAuthorizationError`: an RPC caller receives `authorization_failed`, and
an event is rejected terminally.

```python
from tori_py import ExecutionContext


class Maintenance:
    def __init__(self) -> None:
        self.enabled = False


class MaintenanceGuard:
    async def can_activate(self, context: ExecutionContext) -> bool:
        maintenance = await context.resolver.resolve(Maintenance)
        assert isinstance(maintenance, Maintenance)
        return not maintenance.enabled
```

### Pipes

A pipe runs once per bound payload, header, or headers argument, in declaration
order, and returns the value the handler receives. `metadata.binding_kind` is
`"payload"`, `"header"`, or `"headers"`, and `metadata.source_name` is the header
name for a single header:

```python
from tori_py import ArgumentMetadata


class TrimTenant:
    async def transform(self, value: object, metadata: ArgumentMetadata) -> object:
        if metadata.binding_kind == "header" and metadata.source_name == "tenant":
            return str(value).strip().lower()
        return value
```

### Interceptors

An interceptor wraps everything after the pipes, including the handler. It can
time the call, add logging context, or translate exceptions. Translate in an
interceptor or in the handler, not in a filter:

```python
from collections.abc import Awaitable, Callable

from tori_py import ExecutionContext, PipelineResult
from tori_py_microservices import PublicRpcError


class OutOfStock(Exception):
    pass


class PublicErrors:
    async def intercept(
        self,
        context: ExecutionContext,
        next: Callable[[], Awaitable[PipelineResult]],
    ) -> PipelineResult:
        try:
            return await next()
        except OutOfStock as error:
            raise PublicRpcError("out_of_stock", "The item is out of stock.") from error
```

Each `next` callback may be awaited once.

### Filters

A message filter can only replace a failure with a successful result. Return
`PipelineResult.from_value(value)`; the value is validated against the handler's
return annotation and encoded like a normal result. A filter that raises or
returns nothing passes the original error to the next filter. A native response
from `PipelineResult.from_response()` is rejected with
`MessageConfigurationError`.

```python
from tori_py import ExecutionContext, PipelineResult


class EmptyQuoteOnTimeout:
    async def catch(self, error: Exception, context: ExecutionContext) -> PipelineResult:
        if isinstance(error, TimeoutError):
            return PipelineResult.from_value(Quote(sku="unknown", total_cents=0))
        raise error
```

### Register Components

Use the normal decorators on a message controller or handler method, or the
service-wide `global_pipeline`:

```python
from typing import Annotated

from tori_py import controller, use_guards, use_interceptors
from tori_py_microservices import MicroservicesOptions, Payload, PipelinePlan, rpc


@controller()
@use_guards(MaintenanceGuard)
class PricingController:
    @rpc("quote")
    @use_interceptors(PublicErrors())
    async def quote(self, request: Annotated[QuoteRequest, Payload()]) -> Quote: ...


options = MicroservicesOptions(
    global_pipeline=PipelinePlan(pipes=(TrimTenant(),)),
)
```

An instance is used as is. A class token such as `MaintenanceGuard` is resolved
as a provider in each delivery's work scope, so register it explicitly, for
example `ClassProvider(MaintenanceGuard)`, in a module visible to the
controller. Unlike HTTP guards, message pipeline classes do not become implicit
providers: an unregistered token fails startup with `HandlerCompilationError`.
See the [configuration reference](configuration.md#global-message-pipeline) for
where global provider tokens must be visible.

### How Failures Reach the Caller

| Handler or pipeline outcome | RPC reply | Event delivery |
| --- | --- | --- |
| `PublicRpcError(code, message, ...)` | `RemoteRpcError` with that code and message | Terminal reject |
| `MessageAuthorizationError`, including a guard denial | `authorization_failed` | Terminal reject |
| `MessageRetryableError` | `temporarily_unavailable`, `retryable=True` | Bounded retry for reliable subscriptions |
| `MessageRejectedError` | `invalid_request` | Terminal reject |
| Any other exception | `internal_error` | Bounded retry for reliable subscriptions |

## Response And Error Contract

A normal result is encoded into a response with the original correlation ID. To
expose an expected application failure, raise `PublicRpcError`:

<!-- docs-test: raises PublicRpcError -->

```python
from tori_py_microservices import PublicRpcError

raise PublicRpcError(
    "not_found",
    "Catalog item was not found.",
    retryable=False,
    details={"resource": "catalog-item"},
)
```

The caller receives `RemoteRpcError` with the stable code, public message,
retryable advisory, and safe details. Unexpected exceptions are replaced by a
sanitized `internal_error`; Python exception types, arguments, module paths, and
tracebacks never cross the wire. Authorization, validation, and explicitly
retryable handler failures also map to stable sanitized responses.

The responder follows this order:

1. Complete the handler pipeline and work-scope cleanup.
2. Encode a result or sanitized error.
3. Publish the reply with `mandatory=True` and await a publisher confirm.
4. ACK the original request only after a definitive routed reply outcome.

If the generated reply route is proven deleted, the server attempts a terminal
request ACK rather than intentionally requeueing work to a route that cannot
recover. If reply publication or ACK is uncertain, the request may redeliver.

## Deadlines Are Not Cancellation

Every client call has one finite positive timeout. One monotonic budget covers
transport readiness, request publication, publisher confirmation, and reply
wait. Each phase consumes the same budget; it does not receive a fresh timeout.

The request also contains an absolute UTC `deadline_at`, and RabbitMQ receives a
message expiration. Before provider/controller resolution, the server rejects
expired requests and deadlines beyond `MicroservicesOptions.max_accepted_rpc_timeout`.
Synchronize deployment clocks; broker expiration is the primary backlog bound
and the UTC timestamp is a defensive server check.

Once a non-expired request enters its work scope, later deadline expiry does not
cancel the handler or roll back its transaction. Caller timeout and cancellation
stop local waiting only.

## Interpret Client Outcomes

| Client outcome | What is known | Safe default |
| --- | --- | --- |
| `UnknownServiceError` | No route existed for this service/version at publication | Fix routing/deployment; do not reinterpret as a business result |
| `RemoteRpcError` | A correlated remote error response arrived | Apply policy to its stable code; `retryable=True` is advisory only |
| `RpcProtocolError` | A correlated reply was malformed or violated the response type | Treat as an integration defect |
| `RpcTimeoutError` | The local deadline elapsed | The request may still execute or have committed |
| `RpcOutcomeUnknownError` | Reply transport was lost or request publication could not be resolved | Reconcile by business identity before any retry |
| `TransportIndeterminateError` | A lower-level publish/settlement result is unknown | Do not automatically repeat the operation |
| caller cancellation | Local work stopped waiting | Do not infer remote cancellation |

The transport never automatically resends an accepted or indeterminate RPC.
Retries require an application decision and, for effectful operations, an
application idempotency key with persistent deduplication/result policy.
Framework `message_id` and `correlation_id` values are transport identities, not
business idempotency keys.

## Replicas And Capacity

Replicas use the same complete `ServiceIdentity` and consume from one service
queue. RabbitMQ balancing is competing-consumer delivery, not strict round
robin. Prefetch, active handler concurrency, pending client calls, and proxy
caches are finite and configurable through `MicroservicesOptions` and
`ServiceClusterOptions`.

One busy method shares the service-wide queue and semaphore with every other
method. This is deliberate service-cluster backpressure. If methods require
independent deployment and capacity, they likely belong to different logical
services rather than per-method queues.

For strongly typed calls and shared client/server contracts, continue with
[Clients And Contracts](clients-and-contracts.md).
