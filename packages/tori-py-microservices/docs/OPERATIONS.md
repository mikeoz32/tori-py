# ToriPy Microservices Operations Guide

## Broker Configuration

Use one RabbitMQ credential and vhost permission set per service. Configure
TLS with an `amqps://` URL and `tls=True`; use `amqp://` with `tls=False` for a
non-TLS development broker. The adapter rejects scheme/TLS mismatches and
does not allow URL flags that silently disable certificate verification.

```python
from tori_py_microservices import RabbitMqOptions

options = RabbitMqOptions(
    "amqps://service-user:password@rabbitmq.example/vhost",
    tls=True,
    connection_name="catalog-api",
)
```

Keep credentials in deployment configuration. Do not put passwords, reply
tokens, payloads, member identifiers, or remote error text in logs or metric
labels.

## Permissions And Topology

Grant only the `configure`, `write`, and `read` permissions required for the
service exchanges, queues, bindings, and reply route. Restrict target routing
keys with RabbitMQ topic permissions when services share an exchange. Quorum
queues are used where durable retry/dead-letter retention is required; retry
queues are delayed and bounded.

## Readiness And Observability

Readiness is the transport state, not the result of one successful publish.
Monitor bounded-cardinality metrics for:

- connection and transport status transitions;
- pending RPC count and request timeout count;
- publisher-confirm latency and indeterminate publication count;
- queue depth, redelivery count, retry depth, and dead-letter depth;
- graceful shutdown failures and callback/task drain failures.

Use namespace, service, contract version, method alias, and bounded outcome
codes as labels. Never use message IDs, correlation IDs, payload values,
credentials, or arbitrary exception text as labels.

## Recovery And Uncertainty

On connection loss, the manager fences the generation, revalidates topology,
reopens consumers, and reports ready only after recovery. Old delivery tags are
not settled on replacement channels. Pending client calls from the old reply
route fail with an outcome-unknown error. A new request waits for the new reply
route.

An accepted or indeterminate RPC must be resolved by application policy. Do not
automatically resend it. Use an idempotency key and an application-owned inbox
or deduplication record when a business operation permits a later retry.
Caller cancellation is not remote cancellation. Duplicate execution and
duplicate or late replies are valid at-least-once outcomes; late replies are
settled and discarded when their correlation is no longer pending.

## Retry, DLX, And Quarantine

Handler failures for reliable events may enter the bounded delayed retry path.
After the configured delivery limit, RabbitMQ dead-letters the message. A
quarantine/replay operation is an application or operations tool: inspect the
dead-letter payload under the service's access policy, correct the cause, and
republish deliberately with a new operational decision. Do not treat a DLX as
an implicit RPC retry mechanism.

Malformed wire data, unknown event schema, invalid settlement state, and
unroutable mandatory publications remain typed failures. They are not converted
to successful processing merely to keep a consumer moving.

## Shutdown

Quiescence first closes admission, then stops consumer intake, drains accepted
callbacks and message tasks, and finally closes native resources. Cancellation
is not swallowed as a normal handler failure. If a cancellation-resistant task
or callback remains after its shutdown budget, shutdown reports the failure
instead of claiming clean completion.

## Release Verification

Run all commands through `uv` from the repository root:

```text
uv build --package tori-py --clear --out-dir DIST_DIR
uv build --package tori-py-microservices --out-dir DIST_DIR
uv run pytest packages/tori-py-microservices/tests -q
uv run pytest examples/tori_py/microservices packages/tori-py-microservices/tests/test_artifacts.py -q
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run ty check tests packages/tori-py-cqrs-core/src packages/tori-py-cqrs-core/tests packages/tori-py-cqrs-event-sourcing-core/src packages/tori-py-cqrs-event-sourcing-core/tests packages/tori-py-cqrs-fastapi/src packages/tori-py-cqrs-fastapi/tests packages/tori-py/src packages/tori-py/tests packages/tori-py-cqrs/src packages/tori-py-cqrs/tests packages/tori-py-cqrs-event-sourcing/src packages/tori-py-cqrs-event-sourcing/tests packages/tori-py-openapi/src packages/tori-py-openapi/tests packages/tori-py-sqlalchemy/src packages/tori-py-sqlalchemy/tests packages/tori-py-microservices/src packages/tori-py-microservices/tests packages/tori-py-persistent-streams-core/src packages/tori-py-persistent-streams-core/tests packages/tori-py-persistent-streams/src packages/tori-py-persistent-streams/tests packages/tori-py-persistent-streams-rabbitmq/src packages/tori-py-persistent-streams-rabbitmq/tests examples/tori_py
uv run python packages/tori-py-microservices/scripts/verify_docs.py
uv run python packages/tori-py-microservices/scripts/verify_artifacts.py DIST_DIR
uv run python packages/tori-py-microservices/scripts/verify_artifacts.py DIST_DIR RABBITMQ_URL

The artifact script must be run once without the RabbitMQ extra to prove lazy
imports and once with the extra plus a disposable RabbitMQ broker to prove the
real connection/transport smoke path. Keep the exact test output and the
artifact inventory with the release review.
