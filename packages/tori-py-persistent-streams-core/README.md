# tori-py-persistent-streams-core

`tori-py-persistent-streams-core` defines framework-neutral, asynchronous contracts for an
append-only partitioned log. It includes an in-memory semantic reference and
adapter conformance helper, but no durable or production storage adapter.

Runtime code depends only on the Python 3.14 standard library. Records contain a
caller-supplied UUID, an opaque byte partition key and payload, immutable byte
headers, and partition-local sparse offsets. The package promises at-least-once
processing: a handler completes before its resume cursor advances, and a failed
record stops its partition without retrying or skipping it.

```python
from uuid import uuid4

from tori_py_persistent_streams_core import (
    AppendRequest,
    Beginning,
    CheckpointStrategy,
    ConsumerRunner,
    InMemoryPersistentLog,
    StreamDefinition,
    Subscription,
)

log = InMemoryPersistentLog()
await log.declare_stream(StreamDefinition("events", 3))
await log.append("events", AppendRequest(uuid4(), b"member-1", b"payload"))
lease = await log.acquire(
    Subscription("events", "projection-v1", "worker-1", Beginning()),
    0,
    strategy=CheckpointStrategy.BROKER_MANAGED,
)
await ConsumerRunner().run_once(lease, handler, limit=10)
await lease.release()
```

Use `ExternalCheckpointStrategy("stable-store-id", store)` instead of
`CheckpointStrategy.BROKER_MANAGED` for application-owned cursors. One group is
bound to that stable identity; the in-memory reference also requires the exact
store object. External checkpoints are not atomic with handler side effects;
handlers must tolerate duplicate delivery. External persistence failures are
typed and retain their original cause and relevant cursor.

Broker-managed checkpoints are supported only in explicitly configured
single-instance deployments. A shared external checkpoint store supports
multi-replica deployments only when every replica uses a replica-unique owner ID
and the store provides atomic fence replacement and exact-owner save validation.

Start modes are `Beginning`, `End`, `ExactOffset`, `Timestamp`, and
`RelativeTime`. Existing progress always overrides a configured start. Retained
history gaps raise `RetentionGapError` and are never reset automatically. Each
log exposes immutable `start_mode_capabilities`; unsupported starts fail before
ownership or intake. `StreamLimits.max_relative_age_days` bounds relative starts.

Custom partition routers are immutable pure value contracts. `StreamDefinition`
defensively copies their identity and configuration so later caller mutation
cannot change routing; non-copyable or invalid routers are rejected.

A lease has at most one in-flight record and can checkpoint only the exact record
it delivered. Forced ownership transfer waits for that delivery to checkpoint,
stop, or release, so old and new owner handlers cannot overlap.

Future adapters must invoke `tori_py_persistent_streams_core.testing.run_conformance_suite`
with an isolated async factory. Portable cases are required; controlled
retention setup is capability-gated. Adapter-specific durability, clustering,
and outage tests remain the adapter's responsibility.

Use [`tori-py-persistent-streams`](../tori-py-persistent-streams/README.md) for
ToriPy handler discovery, execution pipelines, and typed publishers. The
[`tori-py-persistent-streams-rabbitmq`](../tori-py-persistent-streams-rabbitmq/README.md) adapter
documents its narrower production capabilities and operational limits.
