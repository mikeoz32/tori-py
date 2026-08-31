# Persistent Streams

Persistent streams are replayable, append-only, partitioned logs. Producers append
records to a logical stream; consumer groups process each physical partition in
offset order and persist independent progress.

Tori Py separates this technique into three packages:

| Package | Responsibility | Production storage |
| --- | --- | --- |
| `tori-py-persistent-streams-core` | Framework-neutral records, routing, logs, leases, checkpoints, and conformance | No |
| `tori-py-persistent-streams` | Tori Py modules, handler discovery, pipelines, publishers, readiness, and shutdown | Adapter-dependent |
| `tori-py-persistent-streams-rabbitmq` | RabbitMQ native Streams and Super Streams adapter | Provisional and conditional |

Install only the layer the application needs:

```console
uv add tori-py-persistent-streams-core
uv add tori-py-persistent-streams
uv add tori-py-persistent-streams-rabbitmq
```

The RabbitMQ distribution depends on the other two, so the last command is enough
for a Tori Py application backed by RabbitMQ.

## Choose a Guide

- [Core concepts](core.md) covers stream definitions, deterministic routing,
  starts, reads, leases, `ConsumerRunner`, at-least-once processing, and poison
  records.
- [Handlers and publishers](handlers-and-publishers.md) covers Tori Py bindings,
  typed codecs, controller handlers, parameter markers, pipelines, all three
  publisher surfaces, runtime status, readiness, and publication admission.
- [Checkpoints and retention](checkpoints-and-retention.md) covers cursor meaning,
  broker and external strategies, ownership fencing, duplicate windows,
  retention gaps, and governed reset decisions.
- [Adapters](adapters.md) describes the `PersistentLog`,
  `PersistentStreamAdapter`, and `StreamAdapterFactory` boundaries and the two
  separate conformance responsibilities.
- [RabbitMQ](rabbitmq.md) documents regular Streams, Super Streams, topology,
  barriers, SAC, tagged cursors, exact implemented limits, TLS/SASL, and the
  adapter's provisional capability profile.
- [Operations](operations.md) provides deployment preflight, monitoring,
  shutdown, incident classification, and recovery procedures.

## Guarantees

The portable contract guarantees:

- Immutable records with caller-assigned UUID identity, a non-empty byte
  partition key, opaque byte payload, and immutable byte headers.
- Deterministic routing to one partition through the stream's frozen router.
- Strictly increasing, potentially sparse offsets and serial delivery within one
  partition.
- Independent progress for each `(stream, consumer group, partition)`.
- Existing progress taking precedence over a newly configured start mode.
- Handler completion before checkpoint advancement.
- Redelivery when effects complete but progress does not definitively advance.
- Fail-stop handling for poison records, checkpoint failures, and retention gaps.
- Finite reads and finite application and adapter capacity controls.

The contract does not guarantee:

- Global ordering across partitions or streams.
- Exactly-once processing or atomicity between handler effects and checkpoints.
- Automatic retries, dead letters, poison-record skipping, or checkpoint repair.
- A publish offset. `PublishReceipt` contains the selected partition and outcome,
  but never a broker offset or `StoredRecord`.
- That an empty read is a permanent end of stream.
- A CQRS, domain-event, event-store, RPC, or microservices bridge.

## Delivery Model

For one partition, successful processing follows this order:

```text
load or initialize resume cursor
-> fetch one retained record
-> decode and run application work
-> finish work-scope cleanup
-> persist the record offset as last successful
-> fetch the next record
```

If application effects commit and the process fails before checkpoint persistence
is known to have succeeded, the record can run again. Make handlers idempotent by
stable business identity or `record_id`, or implement an application-owned inbox
or transactional boundary.

## First Example

The repository includes an executable broker-free Tori Py application with a
typed codec, a pipe, partition metadata, all publisher surfaces, and lifecycle
shutdown:

```console
uv run python -m examples.tori_py.persistent_streams.app
uv run pytest examples/tori_py/persistent_streams
```

It uses the in-memory semantic reference. Process exit loses its streams,
checkpoints, producer state, and ownership, so it is suitable for examples and
tests rather than durable workloads.

## Production Decision

Before selecting an adapter, answer these questions:

1. Which records sharing a business key must remain ordered?
2. Is the partition count and routing algorithm a durable data contract?
3. Which stable consumer-group name owns each independent effect?
4. Can every handler safely run more than once?
5. Who owns checkpoints, and does that store provide atomic fencing?
6. What is the retention period relative to the maximum consumer outage?
7. What explicit decision is allowed when retained history no longer contains a
   required checkpoint?
8. How will publication timeouts and indeterminate outcomes be reconciled without
   automatic resend?
9. Which readiness and blocked-partition signals prevent unsafe traffic?
10. Which adapter-specific release gates remain open?

For RabbitMQ, read both [RabbitMQ capabilities](rabbitmq.md) and
[operations](operations.md) before deployment. Release `0.1.0` is provisional;
it is not an unconditional production-readiness statement.
