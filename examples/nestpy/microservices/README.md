# Nestpy Microservices Examples

These examples are intentionally small and use public APIs. They demonstrate
the contracts without claiming exactly-once delivery, strict round-robin
balancing, live membership, or built-in outbox support.

## Standalone RPC

`rpc_service.py` defines a controller with `add` and `multiply` RPC methods.
Discovery compiles all direct `@rpc` methods from `CalculatorModule`; no
endpoint module or package scanning is required.

## Replicas And Client Cluster

`replicas.py` starts three in-memory replicas with one shared service identity
and queue. `run_competing_replicas()` sends requests through one
`ServiceCluster`. `call_multiple_services()` calls two logical services through
that same shared reply listener. The result reports which replicas handled work;
distribution is competing-consumer balancing, not strict round-robin. A RabbitMQ deployment
uses `RabbitMqModule.for_root(...)`, `RabbitMqTransport`, and
`ClientsModule.register_cluster(...)` instead of the in-memory transports.

## Hybrid Hosting

`HybridReportController` exposes a normal HTTP `GET /reports/health` method and
an RPC `refresh` method from one controller. The application still owns the
HTTP adapter and the microservices root independently.

## Event Modes

`events.py` shows `SERVICE_POOL`, `SINGLETON`, ephemeral `BROADCAST`, and
reliable `BROADCAST`. The reliable broadcast example supplies the stable
`MicroservicesOptions.instance_id` required for durable exclusive ownership.
Durability is adapter-specific; in-memory queues are only test boundaries.

## Deadlines And Outbox

`policies.py` demonstrates an offline deadline and an application-owned outbox
relay boundary. The transport does not persist or relay an outbox on behalf of
the application.

Run the example tests with:

```text
uv run pytest examples/nestpy/microservices -q
```

For a complete four-process application with an HTTP API gateway, three
service-owned PostgreSQL databases, local CQRS, RabbitMQ RPC/events, and an
application-owned outbox, see
[`microservices_app`](../microservices_app/README.md).
