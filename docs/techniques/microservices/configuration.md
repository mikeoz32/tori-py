# Configuration Reference

The microservices package is configured with frozen, validated dataclasses. Each
value is checked when it is constructed, so an invalid limit fails at
composition time rather than under load.

## Service Options

`MicroservicesOptions` configures one logical service. Pass it to
`MicroservicesModule.for_root(identity, transport=..., options=...)`.

```python
from tori_py_microservices import MessageLimits, MicroservicesOptions

options = MicroservicesOptions(
    max_concurrency=16,
    max_inflight_deliveries=64,
    max_accepted_rpc_timeout=10.0,
    message_limits=MessageLimits(max_envelope_bytes=256 * 1024),
)
```

| Option | Default | Meaning |
| --- | --- | --- |
| `max_concurrency` | `32` | Handler invocations that may run at once in this replica |
| `max_inflight_deliveries` | `32` | Unacknowledged deliveries across all consumers of this replica; must be at least `max_concurrency` |
| `max_accepted_rpc_timeout` | `30.0` | Longest remaining RPC deadline, in seconds, the server accepts; longer requests are rejected before any handler runs |
| `max_clock_skew` | `5.0` | How far, in seconds, a request's `created_at` may lie in the future before the server rejects it |
| `message_limits` | `MessageLimits()` | Size and shape limits for envelopes this service decodes and publishes |
| `global_pipeline` | `PipelinePlan()` | Guards, pipes, interceptors, and filters that run for every handler of this service |
| `instance_id` | `None` | Stable instance identity; required by reliable broadcast subscriptions |

Counts must be positive integers and durations finite numbers; `max_clock_skew`
may be `0`. A violation raises `ValueError` or `TypeError`.

The two RPC timing checks protect the server from clients with broken clocks or
unbounded deadlines. A rejected request is settled terminally and is not
retried. Keep deployment clocks synchronized; `max_clock_skew` is a defensive
bound, not a substitute for NTP.

## Message Limits

`MessageLimits` bounds every envelope before or during decoding. The same type
appears in `MicroservicesOptions` and in `ServiceClusterOptions`; give the
service and its clients compatible limits.

| Limit | Default | Bounds |
| --- | --- | --- |
| `max_envelope_bytes` | `1_048_576` (1 MiB) | Encoded size of one envelope; checked before decoding |
| `max_header_count` | `64` | Number of application headers on one message |
| `max_header_bytes` | `65_536` | Encoded size of all headers on one message |
| `max_nesting_depth` | `64` | Depth of nested objects and arrays in a payload or header value |
| `max_collection_items` | `10_000` | Items in any one collection of a payload or header value |

All limits must be positive integers. A message over a limit raises
`WireSizeLimitError` or another `WireValidationError`; inbound messages that
fail are rejected terminally.

## Global Message Pipeline

`global_pipeline` takes a `PipelinePlan` with tuples of `guards`, `pipes`,
`interceptors`, and `filters`. Global components run before controller and
method components of the same kind. Message middleware is not supported, and a
plan with `middleware` fails startup.

<!-- docs-test: skip -->

```python
from tori_py_microservices import MicroservicesOptions, PipelinePlan

options = MicroservicesOptions(
    global_pipeline=PipelinePlan(
        guards=(MaintenanceGuard,),
        interceptors=(TimingInterceptor(),),
    ),
)
```

Each entry is either an instance, used as is, or a provider token such as a
class. Prefer instances for stateless components. A token is checked against
the microservices module at startup but resolved in each delivery's work scope
through the module that owns the handler, so the provider must be visible from
both. Register it in a global module imported at the root:

<!-- docs-test: skip -->

```python
from tori_py import ClassProvider, module


@module(
    providers=[ClassProvider(MaintenanceGuard)],
    exports=[MaintenanceGuard],
    global_=True,
)
class PipelineModule:
    pass
```

A token visible only through `MicroservicesModule.for_root(imports=[...])`
passes startup, but every delivery then fails, and RPC callers receive
`internal_error`. A token that is not registered at all fails startup with
`HandlerCompilationError`.
[Write Pipeline Components](rpc.md#write-pipeline-components) shows each
component kind.

## Client Options

`ServiceClusterOptions` configures one shared RPC client. Pass it to
`ClientsModule.register_cluster(transport, options=...)` or to a manually
created `ServiceCluster`.

| Option | Default | Meaning |
| --- | --- | --- |
| `default_rpc_timeout` | `5.0` | Timeout, in seconds, for calls that do not pass one; at most `max_rpc_timeout` |
| `max_rpc_timeout` | `30.0` | Largest timeout a call may request |
| `max_pending_requests` | `1024` | Calls waiting for replies at once; further calls fail before publication |
| `message_limits` | `MessageLimits()` | Limits for requests this client encodes and replies it decodes |
| `default_namespace` | `None` | Namespace used when `service()` receives only a service name |
| `default_contract_version` | `None` | Contract version used when `service()` receives no version |
| `max_cached_proxies` | `1024` | `ServiceProxy` objects cached by identity |

Keep `max_rpc_timeout` within the server's `max_accepted_rpc_timeout`, or long
calls are rejected by the server.

## Manual Clients and Lifecycle

`ClientsModule.register_cluster()` creates the `ServiceCluster`, starts it with
the application, and closes it on shutdown. A cluster you create yourself is
yours to close:

<!-- docs-test: skip -->

```python
from tori_py_microservices import ServiceCluster, ServiceClusterOptions

cluster = ServiceCluster(
    transport,
    options=ServiceClusterOptions(default_rpc_timeout=2.0),
    manage_transport=True,
)
try:
    await cluster.start()
    quote = await cluster.request(
        CATALOG,
        "quote",
        {"sku": "A-1"},
        response_type=Quote,
    )
finally:
    await cluster.close()
```

`start()` starts the transport if needed and waits until the reply route is
ready. It is optional: the first `request()` starts the cluster within that
call's timeout. `close()` fails every pending call with
`RpcOutcomeUnknownError`, stops reply routing, and closes the transport only when
`manage_transport=True`. A closed cluster cannot be restarted.

## Message Codecs

Envelopes are encoded by a `MessageCodec`. The default is
`MsgspecJsonMessageCodec`, which writes JSON and enforces the configured
`MessageLimits`; module-composed services and clients always use it.

A `MessageCodec` implements six methods:

| Method | Converts |
| --- | --- |
| `encode_request(envelope)` / `decode_request(data)` | `RpcRequestEnvelope` to and from bytes |
| `encode_response(envelope)` / `decode_response(data)` | `RpcResponseEnvelope` to and from bytes |
| `encode_event(envelope)` / `decode_event(data)` | `EventEnvelope` to and from bytes |

A custom codec can be passed only when you construct `ServiceCluster`,
`EventDispatcher`, or `ServiceRuntime` yourself, through their `codec=`
argument. Every producer and consumer of a contract must use compatible codecs,
and a custom codec is responsible for enforcing size and nesting limits before
it allocates decoded values.
