# Distributed Catalog And Orders Application

This tutorial follows the four-process application under
[`examples/tori_py/microservices_app`](https://github.com/mikeoz32/tori-py/tree/main/examples/tori_py/microservices_app).
It demonstrates service-owned data, local CQRS, typed RabbitMQ RPC, an
application-owned outbox relay, and idempotent notification handling.

It is an application architecture example, not a production deployment template.

## Reproducibility Status

The broker-free tests and Docker Compose acceptance path are both declared by
the repository. The frozen development dependency group contains `psycopg` and
Uvicorn, while the example image installs the system `libpq` runtime required by
the pure Python Psycopg package. [`compose.yaml`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/compose.yaml)
uses `postgresql+psycopg` URLs consistently for schema-initialization jobs and
service containers.

The image intentionally synchronizes the repository development group because
this is a source-checkout acceptance example, not a minimal production image.
A production application should define a dedicated locked runtime group and use
a multi-stage, non-root image.

The Compose images use mutable tags (`rabbitmq:4-management`, `postgres:17`, and
the uv Python 3.14 base tag) rather than image digests. Byte-for-byte
infrastructure reproducibility requires pinning resolved image digests outside
this tutorial.

## Prerequisites

Use a repository checkout with:

- Python `>=3.14,<3.15` and `uv` for local Python commands;
- Docker Engine with the Docker Compose plugin for infrastructure;
- network access to retrieve the configured container images and Python
  artifacts during the image build;
- free loopback ports `8000` for the gateway and `15672` for RabbitMQ management;
- enough time for the first workspace image build and PostgreSQL/RabbitMQ health
  checks.

Prepare the local workspace and run the broker-free composition tests:

```text
uv sync --all-packages --all-groups
uv run pytest examples/tori_py/microservices_app -q
```

These tests compile all four application roots without opening broker
connections. Their SQLite repository tests do not prove PostgreSQL isolation,
locking, constraints, pooling, or network behavior.

## Map The Topology

The system has four independent Tori Py applications, one RabbitMQ broker, and
one PostgreSQL server containing three service-owned databases:

```text
HTTP client
    |
    v
api-gateway (HTTP, typed RPC clients, no database)
    |                  |                    |
    | RabbitMQ RPC     | RabbitMQ RPC       | RabbitMQ RPC
    v                  v                    v
catalog             orders             notifications
    ^                  |                    |
    | catalog RPC      | order-created      | service-pool consumer
    +------------------+------ RabbitMQ ----+
    |                  |                    |
catalog database   orders database     notifications database
                    + outbox
```

[`postgres-init/001-create-databases.sql`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/postgres-init/001-create-databases.sql)
creates separate login roles and databases. This script runs only when Docker
initializes a new PostgreSQL data volume. Reusing an existing volume does not
rerun initialization scripts.

## Keep Ownership Explicit

| Process | Owns | Does not own |
| --- | --- | --- |
| [`catalog`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/catalog/app.py) | Catalog ORM metadata, repository, PostgreSQL data, local command/query handlers, and catalog RPC methods | Orders, notifications, HTTP gateway routes |
| [`orders`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/orders/app.py) | Order and outbox tables, local CQRS, orders RPC methods, catalog client dependency, and `order-created` publication | Catalog rows or notification storage |
| [`notifications`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/notifications/app.py) | Notification table, durable event subscription, event deduplication, list/health RPC | Order transaction or outbox state |
| [`api-gateway`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/gateway/app.py) | HTTP routes, msgspec request validation, typed service proxies, readiness policy, and HTTP error translation | A database, local CQRS, or a logical service identity |

Catalog and orders use CQRS only inside their own processes. RabbitMQ carries
integration DTOs, not CQRS `Command`, `Query`, or `Event` objects.

[`common/contracts.py`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/common/contracts.py)
contains the narrow msgspec DTO contract shared across process boundaries.
[`common/services.py`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/common/services.py)
maps Protocol methods to stable `ServiceIdentity` and RPC aliases. ORM rows,
repositories, local handlers, and database metadata remain service-private.

## Follow Typed RPC

The shared service identities are `demo.catalog.v1`, `demo.orders.v1`, and
`demo.notifications.v1`. Each service owns one durable RPC queue and one
`<namespace>.<service>.v<version>.*` topic binding. Methods use distinct routing
keys on that service queue; they do not get per-method queues.

The Protocol methods declare their payload DTO and result type. For example,
`CatalogService.get_item()` maps arguments into `GetCatalogItem` and expects a
`CatalogItem`. `@rpc(CatalogService.get_item)` on the server verifies that the
handler belongs to the same service contract and binds one typed payload.

`ClientsModule.register_cluster()` supplies generic dynamic proxies under the
Protocol tokens. Gateway and orders code therefore call normal async methods:

```text
await catalog.get_item(item_id)
await orders.create_order(item_id, quantity)
await notifications.list_notifications()
```

They do not construct routing keys, untyped dictionaries, reply queues, or
response decoders at each call site.

### Create An Item

The gateway validates `CreateCatalogItem`, calls the catalog proxy, and waits
within the client's finite RPC deadline. RabbitMQ routes the request to the
catalog service queue. `CatalogController` converts the integration payload into
the local `CreateItemCommand`; the local command handler writes only the catalog
database and returns a `CatalogItem` DTO.

Expected application errors cross the wire as stable `PublicRpcError` codes such
as `invalid_request`, `conflict`, or `not_found`. Unexpected server exceptions
are sanitized rather than serializing Python types or tracebacks.

### Create An Order

The order path crosses an additional service boundary:

```text
POST /orders
  -> gateway OrdersService proxy
  -> RabbitMQ orders RPC
  -> OrdersController
  -> local PlaceOrderCommand
  -> CatalogItemLookup.get_item()
  -> RabbitMQ catalog RPC
  -> one orders database transaction:
       insert order
       insert outbox row
  -> return Order through the RPC reply path
  -> gateway returns HTTP 201
```

[`AliasProvider(CatalogItemLookup, CatalogService)`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/orders/app.py#L275-L295)
keeps the command handler dependent on the narrow lookup Protocol instead of the
full service or RabbitMQ implementation.

RPC is still at least once. A timeout or connection loss can leave the remote
outcome unknown, and neither caller cancellation nor an HTTP error cancels work
that already started. The example has no business-command idempotency key, so
the gateway deliberately does not retry create requests automatically.

[`GatewayErrorFilter`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/gateway/app.py#L117-L177)
maps stable business codes and transport outcomes to HTTP. A `504` or `502`
describes what the gateway observed; it is not proof that the remote transaction
rolled back.

## Follow The Outbox And Notification

`PlaceOrderHandler` writes the order and one outbox row in the same
`EntityManager.transaction()`. An order cannot commit without its pending event
record, and an outbox record cannot commit without the order.

[`OutboxRelay`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/orders/app.py#L161-L219)
starts as an application lifecycle provider and polls pending rows:

1. Select a pending row, copy its event identity and payload, increment attempts,
   and commit that state.
2. Publish `order-created` with `require_route=True` and carry the stable outbox
   event ID in the `outbox_event_id` header.
3. After a definitive publisher result, mark the outbox row published in another
   transaction.
4. Log failures and retry the pending row after a bounded sleep.

A crash after publication but before step 3 leaves the row pending and causes a
later duplicate publication. This is expected at-least-once relay behavior.
`require_route=True` proves that a matching route existed; it does not prove a
consumer was online, ran, or committed.

[`NotificationsController.order_created()`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/notifications/app.py#L69-L106)
uses a durable `SERVICE_POOL` subscription named `notification-workers`. All
notification replicas with the same service identity and subscription would
compete on one queue, so scaling changes capacity rather than delivering one
copy to every replica.

The handler checks the stable outbox event ID and inserts a notification with a
unique constraint in one local transaction. A duplicate becomes a successful
no-op. The `IntegrityError` path also handles two concurrent deliveries racing
for the same ID. This is the application-owned idempotent effect that makes
outbox duplicates safe for this consumer.

The example is intentionally minimal. It has no general outbox/inbox library,
lease protocol, reconciliation UI, retention job, or multi-effect workflow.

## Understand Composition And Startup

[`common/infrastructure.py`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/common/infrastructure.py)
contains explicit composition helpers, not a hidden service host:

- `sql_module()` creates one SQLAlchemy root from the service's database URL.
- `rabbit_modules()` creates a RabbitMQ root and one `MicroservicesModule` for an
  explicit service identity.
- `migrate()` runs the example's application-owned `metadata.create_all()` job.
- `serve()` starts one compiled application, waits for `SIGINT` or `SIGTERM`, and
  always calls shutdown.

The Compose startup order is:

1. Start PostgreSQL and RabbitMQ and wait for their container health checks.
2. Run separate catalog, orders, and notifications schema-initialization jobs.
3. Start each broker service after its schema-initialization job exits
   successfully.
4. Start the API gateway after service containers have started.
5. Mark the gateway healthy only when `GET /ready` succeeds.

`/health` checks only the gateway process. `/ready` performs three bounded
health RPCs concurrently. Each service health method also runs `SELECT 1` on its
own database. This is a dependency-aware readiness sample, not a guarantee that
the next call succeeds or that every queue has a live consumer.

The three `migrate.py` files call `metadata.create_all()`:

- [`catalog/migrate.py`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/catalog/migrate.py)
- [`orders/migrate.py`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/orders/migrate.py)
- [`notifications/migrate.py`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/notifications/migrate.py)

This is sufficient for a disposable example but is not migration history. A
production deployment should use reviewed, versioned migrations before replicas
or consumers become ready.

## Start And Inspect Infrastructure

Build and start the acceptance stack from the repository root:

```text
docker compose -f examples/tori_py/microservices_app/compose.yaml up --build
```

In another terminal, inspect state and schema-initialization failures through
Compose:

```text
docker compose -f examples/tori_py/microservices_app/compose.yaml ps
docker compose -f examples/tori_py/microservices_app/compose.yaml logs catalog-migrate orders-migrate notifications-migrate
```

The gateway binds only to `127.0.0.1:8000`. RabbitMQ management binds to
`127.0.0.1:15672` with the educational credentials `demo` / `demo`.

Do not start PostgreSQL or RabbitMQ through Python commands. Docker Compose owns
the tutorial infrastructure; `uv` owns local Python commands.

## Run The End-To-End Smoke Flow

Once the gateway readiness check passes, run:

```text
uv run python -m examples.tori_py.microservices_app.smoke
```

[`smoke.py`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/smoke.py)
does the following through the public HTTP gateway:

1. Wait up to 60 seconds for dependency-aware `/ready`.
2. Create a uniquely named catalog item.
3. Create an order for that item.
4. Read the item and order back and compare typed DTOs.
5. Poll notifications for up to 10 seconds.
6. Require exactly one matching notification and print the complete typed result
   as JSON.

The unique item suffix lets the smoke command run against a retained example
volume without colliding with the catalog name constraint. The notification
assertion proves the normal outbox/event path once; it does not inject broker
disconnects, force duplicate redelivery, or prove recovery behavior.

## Shut Down Deliberately

Stop applications and infrastructure while retaining volumes:

```text
docker compose -f examples/tori_py/microservices_app/compose.yaml down
```

Stop the stack and delete the disposable PostgreSQL and RabbitMQ data:

```text
docker compose -f examples/tori_py/microservices_app/compose.yaml down -v
```

Compose sends termination signals and allows the configured 35-second container
grace period. Broker services use `serve()` to call Tori Py shutdown; Uvicorn
drives gateway ASGI lifespan shutdown. Forced container termination can still
interrupt handlers, outbox publication, settlement, or cleanup, so at-least-once
recovery assumptions remain necessary.

## What The Tests Prove

Run the application-root tests independently of Compose:

```text
uv run pytest examples/tori_py/microservices_app/test_applications.py -q
```

[`test_applications.py`](https://github.com/mikeoz32/tori-py/blob/main/examples/tori_py/microservices_app/test_applications.py)
proves that all four roots compile, an order and outbox row commit together,
duplicate notification events produce one stored effect, newest notifications
sort first, and stable gateway errors map to expected status codes.

These are composition and application-policy tests. They do not open RabbitMQ,
drive the Compose stack, verify publisher confirms, test reconnection, or execute
PostgreSQL-specific behavior. The real-infrastructure smoke path must remain a
separate acceptance check once its locked dependency set is complete.

## Production And Example Limitations

- All package distributions are beta and require a pinned, tested application
  lock before deployment.
- Compose uses plaintext development credentials, plain AMQP, one RabbitMQ
  container, one PostgreSQL container, and no TLS, least-privilege vhosts,
  backup, replication, failover, or secret delivery.
- The image installs development dependencies, copies the checkout, and does not
  demonstrate a non-root or minimal production build.
- `metadata.create_all()` is not a versioned or reversible migration strategy.
- The gateway has no authentication, authorization, rate limiting, browser
  policy, tracing backend, or production ingress configuration.
- Create-item and create-order RPCs have no persisted business idempotency key.
  Timeout and outcome-unknown failures must not be retried blindly.
- The polling outbox relay has no multi-replica lease or row-claim strategy.
  Duplicate publication is expected, and scaling it needs deliberate database
  concurrency policy.
- Notification deduplication covers only this one local effect and retains IDs
  indefinitely. It is not a reusable inbox or global exactly-once guarantee.
- Publisher confirmation, routing, consumer ACK, database commit, and caller
  observation remain separate facts.
- Gateway readiness consumes real RPC and database capacity and is only a
  point-in-time signal. RabbitMQ has no framework-provided live membership
  registry.
- The smoke test exercises a happy path, not disconnect, retry, dead-letter,
  backlog, clock, shutdown-race, or indeterminate-outcome fault matrices.

Continue with [Microservice Operations](../techniques/microservices/operations.md)
for idempotency, outbox/inbox, monitoring, capacity, recovery, and shutdown
policy. Read [RabbitMQ](../techniques/microservices/rabbitmq.md) before changing
topology or treating this local Compose file as deployment guidance.
