# ToriPy Microservices Architecture

## 1. Status and Purpose

This document defines the accepted architecture for the optional
`tori-py-microservices` integration. It combines a NestJS-inspired programming
model with RabbitMQ service-cluster and event-delivery semantics derived from
the strongest parts of Nameko's design.

The implementation order is governed by
[`TORI_PY_MICROSERVICES_IMPLEMENTATION_PLAN.md`](TORI_PY_MICROSERVICES_IMPLEMENTATION_PLAN.md).
Executable phase contracts live under `spec/tori-py-microservices/`.

The integration provides:

- declarative RPC and event handlers on ordinary ToriPy controllers;
- one logical service identity per `NestApplication`;
- startup discovery of every explicitly registered controller;
- a module-qualified, scope-safe invocation pipeline;
- transport-neutral server, client, envelope, codec, and settlement contracts;
- a deterministic in-memory transport for conformance and application tests;
- RabbitMQ request-response, clustered RPC consumers, and event delivery;
- a Python-native asynchronous `ServiceCluster` client;
- bounded startup, quiescence, reconnect, and shutdown behavior.

The integration does not turn an application into independently deployed
services. It supplies a reusable capability that can be adopted where deployment
boundaries and distributed failure semantics are explicitly accepted.

## 2. Design Sources and Deliberate Differences

### 2.1 NestJS concepts retained

The public programming model retains the useful NestJS Microservices concepts:

- controller method decorators for message handlers;
- separate request-response and event-based interactions;
- payload, context, headers, and dependency parameter bindings;
- guards, pipes, interceptors, and exception filters;
- client proxies and pluggable transport strategies;
- hybrid HTTP and broker-hosted applications.

The implementation does not copy NestJS internals, RxJS, arbitrary JavaScript
pattern normalization, or exception serialization.

### 2.2 Nameko concepts retained

The RabbitMQ topology retains these Nameko properties:

- one durable RPC queue per logical service, not per RPC method;
- one topic wildcard binding for the service;
- one distinct routing key per published RPC method call;
- competing consumers for replicas of the same logical service;
- one shared reply listener for calls to the complete service cluster;
- response publication before request acknowledgement;
- `SERVICE_POOL`, `SINGLETON`, and `BROADCAST` event delivery modes;
- event fan-out through distinct broker queues rather than local handler fan-out;
- consumer cancellation before waiting for active work during shutdown.

The implementation replaces Eventlet and blocking calls with native asyncio,
uses typed stable wire errors, requires deadlines for RPC, and gives reconnect
and indeterminate outcomes explicit semantics.

## 3. Package Boundary

The first implementation is one optional distribution:

```text
tori-py-microservices
  -> tori_py
  -> msgspec

tori-py-microservices[rabbitmq]
  -> aio-pika >= 10, < 11
```

The base package MUST import without importing `aio_pika`. RabbitMQ symbols live
under `tori_py_microservices.rabbitmq` and fail with an actionable optional-extra
message when the extra is absent.

`tori_py` MUST NOT import `tori-py-microservices`, RabbitMQ, or `aio-pika`.
`tori-py-microservices` MUST NOT import Starlette, SQLAlchemy, CQRS, event
  sourcing, Alembic, or application modules.

The package layout is expected to converge on:

```text
packages/tori-py-microservices/
  src/tori_py_microservices/
    __init__.py
    bindings.py
    client.py
    codecs.py
    compiler.py
    context.py
    decorators.py
    envelopes.py
    errors.py
    events.py
    inmemory.py
    module.py
    options.py
    pipeline.py
    runtime.py
    transport.py
    rabbitmq/
      __init__.py
      client.py
      connection.py
      context.py
      options.py
      server.py
      topology.py
    py.typed
  tests/
  scripts/verify_artifacts.py
```

## 4. Terminology

- **Service**: one independently addressable logical RPC target with a stable
  identity and one application-owned handler registry.
- **Replica**: one running `NestApplication` with the same service identity as
  its peers.
- **Service cluster**: every live replica consuming from the same service RPC
  queue.
- **RPC method**: one stable method alias mapped to one decorated controller
  method.
- **Event**: a one-way published fact identified by source service, stable event
  alias, and schema version.
- **Subscription**: a stable consumer-owned event processing identity.
- **Delivery attempt**: one broker delivery of one message to one consumer.
- **Settlement**: acknowledgement, retry/requeue, or terminal rejection of an
  inbound delivery.
- **Broker acceptance**: publisher confirmation that RabbitMQ accepted a
  publication; it is not evidence of consumer execution.

## 5. One Service per Application

One `NestApplication` has at most one `MicroservicesModule.for_root()` service
root. Any second root, including one repeating the same identity under another
key, is a startup error. This invariant keeps lifecycle and controller ownership
unambiguous and lets every registered controller participate without service
markers or endpoint modules.

```python
microservices = MicroservicesModule.for_root(
    identity=ServiceIdentity(
        namespace="kinker",
        name="members",
        contract_version=1,
    ),
    transport=RabbitMqTransport(key="default"),
)
```

`ServiceIdentity` is immutable and validates:

- non-empty namespace and service segments;
- `[a-z][a-z0-9_-]{0,62}` lowercase ASCII aliases, excluding `.`, `*`, and `#`;
- a positive contract version;
- a stable normalized label used in topology and diagnostics.

RPC method, event, subscription, and configured stable instance aliases use the
same grammar. Generated process instance identities use 32 lowercase hex
characters. Every composed AMQP exchange, queue, binding, and routing key must
fit the RabbitMQ 255-byte short-string limit or configuration fails before I/O.

The identity is application configuration, not controller metadata. A service
may expose any number of controllers across any number of normal ToriPy modules.

Multiple logical services in one process are explicitly deferred. If later
required, they need an opt-in ownership model rather than weakening the default
application-wide invariant.

## 6. Module API

The intended base API is:

```python
class MicroservicesModule:
    @classmethod
    def for_root(
        cls,
        identity: ServiceIdentity,
        *,
        transport: ServerTransportFactory,
        options: MicroservicesOptions | None = None,
        imports: Iterable[ModuleImport] = (),
        key: str = "default",
    ) -> DeferredModule: ...
```

The descriptor registers only integration infrastructure. Controllers remain
declared through ordinary `@module(controllers=[...])` metadata. There are no
`RpcModule`, endpoint-module lists, controller lists, package scans, or mutable
global handler registries.

`MicroservicesOptions` owns immutable transport-neutral policy:

- service-wide maximum concurrent deliveries;
- global RPC/event pipeline bindings;
- maximum accepted server deadline;
- payload/header limits;
- shutdown behavior delegated to the application deadline;
- event and RPC failure classification defaults;
- optional stable service instance identity for reliable broadcast.

Transport-specific connection and topology settings do not belong in
`MicroservicesOptions`.

The initial server defaults are intentionally finite: `max_concurrency=32`,
`max_inflight_deliveries=32`, `max_accepted_rpc_timeout=30.0` seconds, a 1 MiB
encoded envelope, 64 headers, 64 KiB aggregate header bytes, nesting depth 64,
and 10,000 decoded collection items. Every limit is independently configurable
downward or upward; non-positive and internally inconsistent values fail
configuration.

## 7. Controller Discovery

The handler compiler injects ToriPy `DiscoveryService` and calls
`get_controllers()` after the final graph, including testing overrides, exists.
It examines every explicitly registered controller in deterministic compiled
order.

For each controller implementation, the compiler inspects only methods directly
declared in `controller.__dict__`. Inherited handler metadata is ignored. This
matches current ToriPy HTTP mapping behavior and avoids accidental inherited
published interfaces.

Discovery performs no package import, filesystem scan, subclass enumeration, or
runtime provider registration. A class that is not an explicit ToriPy controller
cannot become a message entry point merely because it has a decorator.

Each compiled handler plan retains:

- exact owning `ModuleId`;
- exact canonical controller `ProviderRef`;
- controller type and method name;
- stable RPC method or event identity;
- precompiled parameter and return annotations;
- qualified controller/method pipeline bindings;
- event delivery policy where applicable;
- deterministic diagnostics identity.

All handler metadata and signatures are validated before RabbitMQ intake opens.

## 8. RPC Programming Model

RPC methods use an explicit stable alias:

```python
@controller("/profiles")
class ProfilesController:
    @rpc("resolve-profile")
    async def resolve_profile(
        self,
        request: Annotated[ResolveProfileRequest, Payload()],
        context: Annotated[RpcContext, Context()],
    ) -> ResolveProfileResponse:
        ...
```

The decorator stores mapping metadata only. It does not store service identity,
queue names, transport options, controller groups, or module references.

RPC method aliases are lowercase ASCII topic segments and cannot contain `.`.
Aliases are unique across every controller in the application. Duplicate aliases
fail startup even when they occur in different modules or controller classes.

RPC handlers MUST be async. They MUST declare a response annotation. A response
annotation may be `None`, but absence of an annotation is invalid because the
wire contract must be explicit.

## 9. Parameter Binding

Message handlers use `Annotated` markers:

- `Annotated[T, Payload()]` binds and decodes the complete payload;
- `Annotated[T, Payload("field")]` binds one explicit payload field;
- `Annotated[RpcContext, Context()]` binds the transport-neutral RPC context;
- `Annotated[EventContext, Context()]` binds the event context;
- `Annotated[Mapping[str, object], Headers()]` binds immutable safe headers;
- `Annotated[T, Header("name")]` binds one explicit header;
- `Annotated[T, Inject(token)]` resolves a normal ToriPy provider.

Every non-`self` parameter requires exactly one supported marker. Variadic
parameters are invalid. A handler has at most one complete `Payload()` binding.
Context annotation must accept the concrete context type supplied by the
transport.

Raw native broker messages are not default handler arguments. A transport
context subtype may expose a read-only native object through an explicit
`unwrap()` escape hatch. It MUST NOT expose unrestricted settlement methods.

## 10. Handler Pipeline

RPC and event executors reuse ToriPy's driver-neutral `Guard`, `Pipe`,
`Interceptor`, `ExceptionFilter`, `ArgumentMetadata`, `PipelineResult`, and
pipeline metadata decorators. They do not reuse the HTTP `PipelineExecutor`.

Execution order is:

```text
filter boundary(
  global guards -> controller guards -> handler guards ->
  bind arguments ->
  global pipes -> controller pipes -> handler pipes ->
  global interceptors -> controller interceptors -> handler interceptors ->
  handler -> result validation/encoding
)
```

HTTP middleware is not applied to broker messages. Message middleware may be
designed later only if it has semantics distinct from interceptors.

Provider-backed pipeline components resolve from the handler owner's message
work scope. Direct instances are externally owned. Because optional integration
metadata is discovered after graph compilation, implementation classes used as
message pipeline components MUST be explicitly registered providers; the HTTP
implicit fallback-provider convenience does not apply.

`RpcContext.execution_kind == "rpc"` and
`EventContext.execution_kind == "event"`. The context exposes immutable IDs,
metadata, exact handler identity, scoped resolver, and invalidatable scope
lease. It does not expose an HTTP request.

## 11. Per-Delivery Work Scopes

Every delivery attempt executes through:

```python
await work_scopes.run_in(handler.owner_module, invocation)
```

This guarantees:

- one fresh ToriPy work scope per delivery attempt;
- one request-scoped provider instance per delivery;
- exact module visibility for controller dependencies and pipeline providers;
- no inherited HTTP or unrelated message `ContextVar` state;
- application tracking for shutdown and cancellation;
- resource cleanup before settlement.

Controller instances remain ToriPy singleton controllers. Message-specific
state belongs in handler arguments or request-scoped dependencies, not mutable
controller attributes.

Settlement MUST occur only after interceptors and work-scope resource cleanup.
For events, ACK eligibility requires successful handler completion. For RPC, a
successful result or a handled/sanitized wire-error outcome is ACK-eligible once
its reply reaches a definitive publication outcome. A scope finalization failure
is a delivery failure even if the handler returned a value or error response.

## 12. Transport Contracts

The base package defines transport-neutral contracts for:

- inbound encoded delivery and immutable broker metadata;
- outbound publication;
- request-response reply publication;
- server registration and intake control;
- client request and event publication;
- delivery settlement outcomes;
- connection and server status updates;
- native driver escape hatches.

A server transport receives an immutable compiled registry and one framework
dispatcher callback. It does not resolve providers, inspect decorators, execute
pipeline components, or own ToriPy work scopes.

A transport reports delivery facts but does not claim universal semantics.
RabbitMQ competing consumers, a future Kafka consumer group, and an in-memory
test broker may implement the same interface while retaining documented
differences in ordering, redelivery, and broker acceptance.

## 13. In-Memory Reference Transport

The base distribution contains a deterministic in-memory transport used for:

- transport conformance tests;
- application tests without RabbitMQ;
- handler compiler and pipeline acceptance;
- multiple simulated replicas sharing one broker object;
- RPC correlation, timeout, and event-mode tests.

It MUST model explicit acceptance, bounded queues, manual settlement, competing
consumers, redelivery, and reply correlation. It MUST NOT claim persistence or
process-failure durability.

The in-memory transport is not a replacement for RabbitMQ integration tests.

## 14. RabbitMQ Root and Ownership

RabbitMQ resources are configured through a keyed root:

```python
rabbit = RabbitMqModule.for_root(
    RabbitMqOptions(...),
    key="default",
)

microservices = MicroservicesModule.for_root(
    ServiceIdentity("kinker", "members", 1),
    transport=RabbitMqTransport(key="default"),
    imports=[rabbit],
)
```

One RabbitMQ root owns one robust connection. Separate channels are used for:

- RPC/event consumption;
- publisher-confirm publications;
- reply consumption and correlation.

Sharing a connection does not permit sharing channel-scoped delivery tags.
Every delivery is settled on the channel that received it.

Owned connections are managed singleton resources. Externally supplied
connections may be supported later only with explicit non-ownership semantics.

## 15. RabbitMQ RPC Topology

RabbitMQ RPC uses one durable topic exchange:

```text
exchange: tori_py.rpc
type: topic
durable: true
```

Each logical service owns one durable queue:

```text
queue: tori_py.rpc.<namespace>.<service>.v<contract_version>
```

The queue has exactly one service wildcard binding:

```text
binding key: <namespace>.<service>.v<contract_version>.*
```

Each request is published with the method-specific routing key:

```text
<namespace>.<service>.v<contract_version>.<rpc_method>
```

For example:

```text
queue:       tori_py.rpc.kinker.members.v1
binding:     kinker.members.v1.*
routing key: kinker.members.v1.resolve-profile
routing key: kinker.members.v1.suspend-profile
```

There is no queue or binding per method. The selected replica extracts the
method segment and dispatches through its immutable local RPC registry.

An unknown service or contract version has no matching binding. Mandatory
publication with publisher confirms therefore raises `UnknownServiceError` when
the message is returned as unroutable. A known service with an unknown method is
routed to the service queue and receives a typed `method_not_found` response.

A durable queue may remain after every replica stops. In that case the request
is routable but has no active consumer; mandatory publishing cannot detect this.
The caller deadline and broker expiry are authoritative. Runtime code MUST NOT
pretend to know live replica count without a separate presence protocol.

## 16. Replica Balancing and Backpressure

Every replica of one service identity registers one consumer on the same service
queue. RabbitMQ competing-consumer delivery provides cluster balancing.

The wildcard binding is important because all methods enter one service-wide
queue and therefore share one capacity domain. Separate method queues would
allow one replica to accumulate work independently per method and would not
represent Nameko-style service-cluster balancing.

Required configuration:

- equal consumer priority across replicas;
- no exclusive RPC consumer;
- no single-active-consumer option;
- bounded per-consumer prefetch;
- manual acknowledgement;
- one service-wide concurrency limiter per replica.

The sum of prefetch allocations across the replica's RPC and event consumers is
at most `max_inflight_deliveries`; each active consumer receives at least one.
Startup rejects a consumer set larger than that bound. The RPC consumer receives
up to `max_concurrency`, constrained by the remaining shared budget. Unlimited
or independently multiplied per-subscription prefetch is invalid. RabbitMQ
delivery is not promised to be mathematically strict round-robin: outstanding
unacknowledged messages, connection timing, consumer capacity, and broker
behavior affect the observed distribution.

## 17. RPC Request Envelope

The canonical request envelope contains:

```text
message_id
kind = rpc_request
namespace
service
contract_version
method
schema_version
created_at
deadline_at
correlation_id
causation_id
reply_to
headers
payload
```

Stable aliases never use Python module or class paths. IDs use canonical UUID
text. Timestamps use UTC. Headers are immutable, size-limited, string-keyed, and
restricted to codec-supported values.

`message_id` identifies one transport message and remains stable across broker
redelivery. It is not a business idempotency key: applications define any
deduplication identity, scope, persistence, and replay policy in their own
payloads and storage.

The default wire codec is deterministic msgspec JSON. A custom codec must
implement the same size, failure, and type-validation contract. Unsafe pickle or
arbitrary Python-object serialization is prohibited.

## 18. Deadline-Bound RPC Backlog

RPC calls require a finite timeout. The client computes one absolute
`deadline_at`, places the remaining duration in RabbitMQ message expiration, and
starts its local wait against the same monotonic budget.

Before resolving a controller or opening a work scope, the server checks the
absolute deadline. An expired request MUST NOT execute business logic or acquire
transactional resources. It is settled without retry and may receive a typed
`deadline_exceeded` response when its reply route remains available.

This permits a durable service queue to buffer short service outages without
allowing stale synchronous commands to execute indefinitely after callers have
given up.

Clock skew remains possible. Broker expiration provides the primary queue-side
limit; the absolute timestamp is a defensive server check and observability
fact. Deployments must synchronize clocks.

Caller cancellation or timeout stops waiting only. It does not prove that an
accepted remote request was cancelled, rolled back, or not committed.

The deadline is an admission and durable-backlog deadline, not remote
cancellation. Once the server admits a non-expired request into a work scope, a
later deadline does not cancel the handler. Only explicit application or
shutdown cancellation can interrupt admitted work.

## 19. RPC Response Protocol

The response envelope contains:

```text
message_id
kind = rpc_response
correlation_id
completed_at
result
error
```

Exactly one of `result` or `error` is present. A wire error contains:

```text
code
message
retryable
details
```

The package never serializes Python exception instances, module paths,
tracebacks, or arbitrary exception arguments. Unexpected exceptions map to a
sanitized internal error and are logged locally with correlation metadata.

The responder publishes a reply with `mandatory=True` and publisher confirms
before settling the original request. A confirmed and routed reply permits ACK.
A publisher NACK or connection/confirm uncertainty leaves the request
unacknowledged and eligible for redelivery. A mandatory return proves that the
generated reply route no longer exists; the server records `reply_route_gone`
and attempts terminal ACK rather than intentionally requeueing work against a
route that cannot recover. ACK connection uncertainty can still cause broker
redelivery.

Consequently RPC handler execution is at least once. A connection can fail
after a database commit or reply publication but before request ACK reaches the
broker. Duplicate execution and duplicate replies are valid failure outcomes.

## 20. ServiceCluster Client

The Python-native client API is asynchronous:

```python
result = await cluster.service(
    ServiceIdentity(namespace="kinker", name="members", contract_version=1)
).request(
    "resolve-profile",
    request,
    response_type=ResolveProfileResponse,
    schema_version=1,
    timeout=2.0,
)
```

The transport-neutral `ServiceCluster` lazily creates immutable service proxies
while sharing:

- one `ClientTransport` runtime;
- one bounded correlation map across all target services;
- one status stream and close operation.

The RabbitMQ `ClientTransport` implementation uses the connection owned by its
imported keyed `RabbitMqModule` root and owns only its publisher-confirm channel
or bounded channel pool plus reply listener/queue. The in-memory implementation
supplies the same client contract without RabbitMQ.

Client registration is explicit and independent of a server root:

```python
clients = ClientsModule.register_cluster(
    transport=RabbitMqTransport(key="default"),
    options=ServiceClusterOptions(
        default_namespace="kinker",
        default_contract_version=1,
    ),
    imports=[rabbit],
    key="default",
)
```

`ServiceClusterOptions` owns `default_rpc_timeout=5.0` seconds,
`max_rpc_timeout=30.0` seconds, `max_pending_rpc=1024`, and optional default
namespace/contract version. It and `MicroservicesOptions` each carry the same
immutable `MessageLimits` value so client publication and server intake enforce
one wire contract. Non-positive or internally inconsistent values fail
configuration.

The canonical proxy key is a complete `ServiceIdentity`. A
`cluster.service("members", version=1)` convenience is valid only when the
cluster was configured with an explicit default namespace; an explicit
`namespace=` overrides that default. Dynamic method attributes are not the
primary API because explicit `request(method, ...)` is clearer and easier to
type.

### Typed Service Contracts

Applications may declare a `typing.Protocol` client contract with
`@service_contract(ServiceIdentity(...))`. Each async method has an explicit
`@rpc_call("method", payload=RequestDto)` declaration. Payload schemas remain
application-owned `msgspec.Struct` types; the framework never infers or
generates distributed schemas from Python signatures.

`ClientsModule.register_cluster(..., contracts=(CatalogService,))` exports one
generic dynamic proxy under each Protocol token. Its `__getattr__` resolves only
precompiled contract methods, caches the resulting async callable, binds normal
Python positional/keyword arguments, converts the named payload fields to the
declared DTO, and delegates to the existing immutable `ServiceProxy`.
`Annotated` keyword-only markers carry envelope metadata such as
`CorrelationId`, `CausationId`, `CallHeaders`, and
`CallTimeout`; those values never become payload fields.

The same Protocol method may be supplied to server `@rpc(Protocol.method)`.
Startup compilation then verifies the handler's complete `Payload()` DTO and
return annotation against the contract. The existing string-based `@rpc("...")`
and `ServiceProxy.request("...", ...)` APIs remain the transport-level escape
hatches; typed contracts add no retries or delivery guarantees.

Publishing uses `mandatory=True` and publisher confirms. Broker acceptance does
not imply handler completion. The client never automatically resends an RPC
request after an accepted or indeterminate publication.

## 21. Reply Queue and Reconnect

The RabbitMQ client uses one classic exclusive auto-delete reply queue with a
bounded expiry. It binds an opaque client-instance reply routing key to the RPC
exchange. Every request has a unique correlation ID stored in a bounded pending
map.

The generated route is exactly `reply.<token>`, where `<token>` is 32 lowercase
hex characters from 128 bits of cryptographic randomness. `reply_to` contains
only that routing key, never an exchange or queue name. Servers accept only this
exact grammar and always publish through `tori_py.rpc`.

On a normal reply:

1. decode and validate the response envelope;
2. find and remove the pending correlation entry;
3. complete its waiter;
4. ACK the reply.

Unknown, timed-out, cancelled, late, and duplicate correlation IDs are logged at
a bounded level, ACKed, and discarded. They never recreate a waiter.

On reply connection loss:

- all pending calls complete with `RpcOutcomeUnknownError`;
- no pending request is automatically republished;
- a replacement reply queue is fully declared and consuming before new requests
  are admitted;
- the old queue identity is never reused;
- late responses to the deleted route are terminally unroutable and cause the
  server to attempt ACK without intentional requeue; ACK uncertainty may still
  redeliver.

This intentionally avoids Nameko's ambiguous pending-reply recovery behavior.

Each pending entry follows one synchronized, exactly-once state machine:

```text
registered -> publishing -> accepted -> completed
                    \-> rejected/unroutable/indeterminate
```

A validated reply may complete an unresolved entry while its publication
confirm is still pending and wins that race. A definitive pre-acceptance NACK or
unroutable return fails only an unresolved entry. Timeout or cancellation before
any write is a local timeout; either while awaiting a confirm is an indeterminate
publication; either after confirmation is an accepted-request timeout. None of
these paths automatically republishes, and every path removes the entry once.

## 22. Event Publication

Each source service publishes to a durable topic exchange:

```text
exchange: tori_py.events.<namespace>.<source_service>.v<contract_version>
```

The routing key is `<event_alias>.v<schema_version>`. Including the payload
schema version prevents concurrently supported schemas from entering each
other's queues. The event envelope contains:

```text
message_id
kind = event
source namespace/service/contract version
event
schema_version
occurred_at
correlation_id
causation_id
headers
payload
```

The injected `EventDispatcher` receives only event alias, schema version,
payload, and explicit metadata; source identity comes from the local service
root. It does not choose `SERVICE_POOL`, `SINGLETON`, or `BROADCAST`; those are
consumer queue semantics.

Its application API is:

```python
await dispatcher.publish(
    "profile-created",
    1,
    payload,
    headers={"trace": trace_id},
    correlation_id=correlation_id,
    causation_id=command_id,
    require_route=False,
)
```

`message_id` and `occurred_at` are generated for each call. `occurred_at` may be
supplied explicitly when an outbox relay must preserve the original domain-event
time. The caller cannot supply a source identity, exchange, routing key,
destination, subscription, consumer mode, or message ID. The dispatcher builds
and validates `EventEnvelope` and `EventIdentity` values with the root's codec
and message limits, then returns the transport `PublicationReceipt`.

`MicroservicesModule` registers and exports one managed singleton dispatcher
only when its transport is a `KeyedTransportFactoryReference`. The dispatcher
uses that reference's exact `client_factory_token`, while `ServiceRuntime` uses
the exact `server_factory_token`; generic composition contains no adapter
knowledge. A legacy direct `ServerTransportFactory` root remains valid for
inbound-only tests and services, but does not provide `EventDispatcher` because
it has no client factory. Attempting to inject the absent dispatcher is rejected
by normal graph compilation.

The client transport is created without native I/O during provider construction.
Application bootstrap starts it in event-only mode without a reply consumer.
Publication is admitted only while running. Quiescence closes admission first,
drains accepted publication tasks against `ShutdownContext.remaining()`, and
shutdown closes the owned client transport without starting another unbounded
drain after the shared deadline. Explicit direct close drains accepted work when
no shared shutdown budget applies. Bootstrap, quiescence, and close are
idempotent and concurrency-safe.

Event publication normally permits zero subscribers. The dispatcher uses
mandatory publication to report whether at least one binding existed, suppresses
the unroutable result unless `require_route=True`, and returns `routed=False` for
the suppressed case. Publisher confirms and routing still do not prove active
consumers or handling.

## 23. Event Handler API

Event handlers remain controller methods and carry consumer mapping metadata:

```python
@event_handler(
    source=ServiceIdentity(
        namespace="kinker",
        name="members",
        contract_version=1,
    ),
    event="profile-created",
    schema_version=1,
    mode=EventDispatchMode.SERVICE_POOL,
    subscription="send-profile-notification",
)
async def profile_created(
    self,
    event: Annotated[ProfileCreatedV1, Payload()],
) -> None:
    ...
```

`mode` is on the consumer decorator, matching Nameko's event-handler model. It
is not an RPC option and is not selected by the producer dispatcher.

The complete source `ServiceIdentity` selects the source namespace, service,
and contract-version exchange. `schema_version` independently selects the event
payload contract. These versions are explicit because a service contract can
publish several concurrently supported event schemas.

Every event handler requires an explicit `subscription`; reliable handlers keep
it stable across deployments. Python controller or method names never become
queue identities. Event handlers MUST be async and MUST declare `None` as their
return type.

`SERVICE_POOL` and `SINGLETON` are always reliable and reject a `reliable`
argument. For `BROADCAST`, omitted or `False` means ephemeral and `True` means
reliable with a configured stable instance identity.

## 24. SERVICE_POOL Events

`SERVICE_POOL` creates one durable queue for one logical handler pool:

```text
<event_queue_prefix>--pool.<destination_namespace>.<destination_service>.v<destination_version>.<subscription>
```

Here and below, `<event_queue_prefix>` is
`tori_py.event.<namespace>.<source>.v<source_version>.<event>.v<schema_version>`.

Every replica of the destination service registers a consumer for the same
queue. One replica receives each delivery attempt. Two handlers for the same
event use distinct subscriptions and therefore distinct queues; each logical
handler pool receives the event independently.

This broker fan-out avoids local multi-handler settlement coupling. Failure of
one subscription does not force successful work in another subscription to run
again.

## 25. SINGLETON Events

`SINGLETON` creates one durable queue per explicit global subscription:

```text
<event_queue_prefix>--singleton.<subscription>
```

Every consumer declaring the same singleton subscription competes for that
queue, regardless of destination service. Exactly one consumer receives each
delivery attempt.

The explicit subscription is required. Reusing a singleton subscription with
incompatible payload or effect semantics is a deployment contract violation.
Singleton delivery is not leader election and does not grant a durable lock
outside one message attempt.

## 26. BROADCAST Events

`BROADCAST` creates one queue per destination service instance:

```text
<event_queue_prefix>--broadcast.<destination_namespace>.<destination_service>.v<destination_version>.<subscription>.<instance_identity>
```

Ephemeral broadcast is the default broadcast form:

- generated process instance identity;
- classic exclusive auto-delete queue;
- no delivery while the instance is offline;
- suitable only for cache invalidation, local wakeups, and presence-like facts.

Reliable broadcast is opt-in:

- explicit stable instance identity;
- durable classic queue;
- mandatory exclusive consumer registration to reject duplicate live instance
  identities;
- bounded queue expiry/retention policy;
- operator responsibility for identity lifecycle and orphan cleanup.

Large durable fan-out or replay requirements may require RabbitMQ Streams or a
future log transport rather than thousands of per-instance queues.

## 27. Event Settlement and Failure Policy

An event is ACKed only after its handler pipeline and work scope close
successfully.

Default classification:

- malformed envelope, unsupported schema, or permanent validation error:
  terminal reject without requeue, normally dead-lettered;
- explicit `RetryableMessageError`: bounded retry/requeue;
- explicit `RejectedMessageError`: terminal reject;
- unexpected ordinary exception: retryable under the configured bounded broker
  delivery policy;
- cancellation, process failure, or connection loss before settlement:
  unacknowledged and eligible for broker redelivery;
- settlement connection uncertainty: close/replace the channel and treat the
  outcome as indeterminate.

Immediate unbounded requeue loops are prohibited. Production durable queues must
have delivery limits and a dead-letter or quarantine policy. Delayed retry is
owned by RabbitMQ policies or an explicitly specified retry topology, not by
sleeping while holding an unacknowledged work scope.

The first RabbitMQ release requires RabbitMQ 4.0 or newer. Quorum retry uses
`reject(requeue=True)` with a finite `delivery-limit` and DLX policy. Reliable
broadcast uses classic queues for exclusive-consumer enforcement and therefore
requires an explicit finite retry/DLX topology with persisted broker-visible
attempt state; without one, retryable failures are terminally dead-lettered.
Dedicated retry exchanges use `<queue>.retry` when that name fits the broker's
127-byte exchange-name limit and otherwise use deterministic
`tori_py.retry.<sha256>` names. Queue identity remains unchanged.

## 28. RabbitMQ Queue Types

Defaults:

- durable RPC service queues: quorum;
- durable `SERVICE_POOL` and `SINGLETON` event queues: quorum;
- RPC reply queues: classic exclusive auto-delete;
- ephemeral broadcast queues: classic exclusive auto-delete;
- reliable broadcast queues: durable classic with exclusive consumer.

Queue type is immutable topology. A declaration mismatch is a startup failure,
not an automatic migration. Dynamic concerns such as dead-letter exchanges,
delivery limits, delayed retry, and queue limits SHOULD use RabbitMQ policies
where possible.

Publisher confirms and consumer acknowledgements are independent. Both are
required for the intended data-safety model.

RPC requests and events use persistent AMQP delivery mode. Replies are transient
because their exclusive route and caller deadline define their lifetime.

## 29. Startup Lifecycle

Server and client runtimes are independent lifecycle-managed ToriPy providers,
not `ApplicationAdapter` instances. The current single adapter remains available
to Starlette. This also supports a standalone application using
`NoopApplicationAdapter`.

Startup sequence:

1. compile the ToriPy module/provider graph;
2. construct singleton providers and controllers;
3. when a service root exists, discover controllers and compile message handlers;
4. validate each present server/client runtime configuration;
5. acquire the broker connection and channels as managed resources;
6. let each server/client runtime declare and verify its topology without
   admitting messages;
7. let the ToriPy kernel open work-scope admission;
8. start RPC/event consumers for each server runtime and the reply consumer for
   each independent client runtime in `on_application_bootstrap()`;
9. await consumer readiness;
10. return from bootstrap, after which normal HTTP admission may open.

Any partial startup failure cancels attempted consumers, closes acquired
channels/resources in reverse order, and prevents application readiness.

Transport intake atomically checks admission and transfers each accepted
delivery to one runtime-owned processing task. A transport callback must not
spawn handler work and return detached. Driver-specific callback accounting and
cancellation fences belong to the transport adapter.

## 30. Quiescence and Shutdown

The runtime implements `on_application_quiesce(context)`:

1. close transport intake admission;
2. cancel RabbitMQ consumers so no new deliveries are accepted;
3. cross the RabbitMQ callback scheduling fence and wait for handoffs to finish;
4. retain and wait for accepted delivery tasks using
   `ShutdownContext.remaining()`;
5. allow their ToriPy work scopes to finish and settle;
6. on deadline cancellation, cancel tasks and leave uncertain deliveries
   unacknowledged or explicitly requeue when safe;
7. wait for callback tails to return after their transferred tasks complete;
8. return so the kernel can close work admission and drain remaining scopes;
9. close server/client-owned channels and reply routing, then let the imported
   RabbitMQ root close its connection through normal resource teardown.

No listener task is detached or unowned. Shutdown never starts unbounded
background cleanup after the application deadline.

## 31. Connection Recovery

The owned robust connection may restore its connection and channels, but all
framework exchange/queue declarations and `consume()` registrations use
`robust=False`. This prevents aio-pika from restoring intake before framework
admission and from reusing a deleted reply queue identity. A framework recovery
coordinator owns topology declaration and consumer registration after the
underlying connection is usable.

On server reconnect:

- topology is revalidated before consumers resume;
- the same stable service/event queues are used;
- deliveries whose old channel closed are considered unsettled and may
  redeliver;
- old channel delivery tags are never reused;
- server status reports reconnecting/not-ready until intake is restored.

On client reconnect, the coordinator generates and consumes a new reply route
before admitting requests. Pending calls from the lost route have already
completed as outcome unknown.

On publisher uncertainty, the caller receives a typed indeterminate publish
error unless RabbitMQ explicitly confirmed acceptance or rejection. Retrying an
event may duplicate it; retrying RPC may duplicate remote execution. Message and
application-owned business IDs must remain stable when application policy permits
a retry.

## 32. Status and Native Access

Server and client components expose:

- a current immutable status;
- an async iterator of distinct status changes;
- readiness suitable for application health integration;
- a typed `unwrap()` escape hatch for advanced driver access.

Connection status is not service membership. A client cannot infer exact live
replica count from routing success. Operational monitoring may inspect RabbitMQ
consumer counts, queue depth, redelivery, and publish-confirm latency outside
the application protocol.

## 33. Observability and Context Propagation

Every invocation logs or measures only bounded non-sensitive fields:

- local service and contract version;
- source or target service;
- method/event alias and schema version;
- message/correlation/causation IDs;
- delivery attempt/redelivery class;
- result, error, and settlement class;
- queue wait, handler, scope cleanup, reply, and total latency;
- reconnect and queue-depth buckets where available.

Member IDs, handles, OIDC subjects, message bodies, content snippets, report
details, and access tokens are not metric labels.

W3C `traceparent`/`tracestate` may be propagated as validated headers without a
required OpenTelemetry dependency. Arbitrary ambient `ContextVar` values and
HTTP headers are never copied automatically. Authentication and authorization
credentials require explicit minimized application policy.

## 34. Security

Production RabbitMQ configuration requires:

- TLS outside a trusted local development environment;
- per-service credentials and vhost permissions;
- exact configure/write/read permissions for owned exchanges, declarations,
  bindings, and service/subscription queues;
- RabbitMQ topic permissions when RPC publishing must be restricted by target
  routing key, because ordinary resource permissions cover the whole shared
  `tori_py.rpc` exchange;
- encoded-body size before parsing, then header/nesting/collection limits after
  structural envelope decoding but before application target construction and
  typed payload decoding;
- safe JSON codecs only;
- sanitized remote errors;
- no trust in routing keys, reply routes, or headers as authorization facts;
- explicit authorization in the handler pipeline or application layer.

At minimum, broker policy maps operations as follows: declaration needs
`configure` on the declared exchange/queue; binding needs `write` on the queue
and `read` on the exchange; consumption needs `read` on the queue; publication
needs `write` on the exchange. Operator-provisioned shared exchanges may remove
application `configure` permission. Target-level restrictions on the shared RPC
exchange require RabbitMQ topic permissions over routing keys.

Reply routes are validated against the transport's generated form before use.
The server does not publish arbitrary attacker-supplied exchanges or routing
destinations.

## 35. CQRS, Persistence, and Application Boundaries

`tori-py-cqrs` remains an in-process application bus. Its existing transport
protocol carries Python messages and exceptions and is not the distributed wire
protocol. An external message handler may translate a validated DTO into an
internal command/query, but there is no automatic bridge.

The integration does not automatically publish CQRS events, domain events, or
event-sourced records. A persisted event is not an integration contract unless
the owning context explicitly translates it.

Reliable application integration events require:

```text
local domain transaction + outbox insert
-> at-least-once relay through EventDispatcher
-> RabbitMQ
-> consumer inbox + local effects in one transaction
-> ACK
```

Outbox, inbox, reconciliation, retention, and consumer-specific minimized
payloads are application or separately specified persistence concerns. A
publisher confirm alone is not a transactional outbox.

Linearizable authorization or policy checks cannot be replaced by eventual
RabbitMQ events without an application-owned consistency protocol. Service
extraction must explicitly define that protocol.

## 36. Testing Strategy

Unit and in-memory tests cover:

- options, aliases, envelopes, codecs, errors, and immutability;
- all-controller discovery with exact module ownership;
- duplicate RPC and event subscription diagnostics;
- parameter and return signature compilation;
- guards, pipes, interceptors, filters, and cancellation;
- singleton/request/transient provider behavior;
- fresh execution context and no HTTP context leakage;
- scope cleanup before settlement;
- deadlines, pending RPC bounds, late replies, and duplicate replies;
- in-memory competing replicas and all event modes;
- deterministic startup rollback and shutdown ordering.

RabbitMQ integration tests cover:

- exact exchange, queue, wildcard binding, and queue-type declarations;
- two and three replicas consuming one service queue;
- several RPC methods sharing one wildcard-bound queue;
- bounded balancing and saturated replica behavior;
- unknown service versus unknown method;
- no-replica deadline-bound backlog;
- publisher confirms, mandatory returns, and unroutable replies;
- crash and connection loss before/after handler, reply, and ACK;
- duplicate execution and duplicate reply handling;
- reconnect topology restoration;
- `SERVICE_POOL`, `SINGLETON`, ephemeral broadcast, and reliable broadcast;
- dead-letter and bounded retry behavior;
- hybrid Starlette and RabbitMQ lifecycle;
- graceful and forced shutdown under active work.

Failure-injection tests SHOULD use a real RabbitMQ service and a network fault
proxy where practical. Unit tests must not require RabbitMQ.

## 37. Public Artifact Contract

The distribution provides:

- exact root and RabbitMQ-subpackage `__all__` inventories;
- `py.typed`;
- stable package-specific errors and diagnostic codes;
- import-boundary tests proving optional dependencies remain lazy;
- isolated wheel and sdist smoke tests;
- no broker connection or user factory execution during import or dynamic
  descriptor materialization.

## 38. Explicit Non-Goals

The first implementation does not provide:

- multiple logical service identities in one `NestApplication`;
- package scanning or automatic controller registration;
- service membership discovery or a live replica registry;
- mathematically strict round-robin guarantees;
- streaming RPC or bidirectional streams;
- remote cancellation guarantees;
- distributed transactions or exactly-once execution;
- automatic command retries;
- automatic CQRS/domain/event-sourcing publication;
- outbox, inbox, saga, or workflow persistence;
- Kafka, NATS, Redis, MQTT, gRPC, or WebSocket transports;
- AsyncAPI generation;
- large-scale replayable broadcast;
- broker-managed authentication or authorization policy;
- framework-generated application message schemas.

## 39. Acceptance Criteria

The architecture is implemented when an application can:

1. register several controllers with simple `@rpc("method")` mappings;
2. discover and compile them once without endpoint modules or package scanning;
3. start several replicas with one service identity and one wildcard-bound RPC
   service queue;
4. balance calls across competing replicas with bounded prefetch;
5. preserve exact module DI and one work scope per delivery;
6. call several target services through one shared `ServiceCluster` reply
   listener;
7. enforce finite RPC deadlines and reject stale backlog without execution;
8. publish confirmed, routed replies before normal ACK, attempt terminal ACK for
   deleted reply routes without intentional requeue, and expose
   duplicate/indeterminate outcomes;
9. execute all three event modes through distinct broker queue topologies;
10. stop intake, drain accepted work, and return unfinished messages safely on
    bounded shutdown;
11. recover connections without silently retrying pending RPC requests;
12. keep ToriPy core, CQRS, persistence, and application boundaries intact;
13. pass package, full regression, quality, documentation, and artifact gates.
