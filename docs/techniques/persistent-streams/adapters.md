# Adapters

Persistent-stream adapters have two separate responsibilities:

1. Implement the framework-neutral `PersistentLog` data and ownership contract.
2. Implement `PersistentStreamAdapter` lifecycle barriers so Tori Py can prepare,
   start, quiesce, drain, and close native intake safely.

Passing tests for one responsibility does not prove the other.

## Package Boundaries

The intended dependency direction is:

```text
application
-> tori-py-persistent-streams
-> tori-py-persistent-streams-core

adapter distribution
-> tori-py-persistent-streams
-> tori-py-persistent-streams-core
-> native driver
```

Core stays framework-neutral and standard-library-only. The Tori Py integration
does not import a broker. An adapter must not make core or the integration import
the native driver in reverse.

Keep infrastructure-specific options, topology, security, and operational claims
inside the adapter distribution.

## PersistentLog Contract

An adapter log implements the public asynchronous surface:

| Member | Required behavior |
| --- | --- |
| `start_mode_capabilities` | Immutable exact support flags |
| `declare_stream(definition)` | Idempotent compatible declaration; typed conflict otherwise |
| `append(stream, request)` | Frozen routing, bounded append, offset-free receipt |
| `bounds(stream, partition)` | Trustworthy bounds or `None`, never inferred append evidence |
| `read(stream, partition, from_offset, limit)` | Finite inclusive partition read with sparse order |
| `acquire(subscription, partition, strategy, transfer=False)` | Fenced exact ownership and cursor initialization |
| `close()` | Idempotent application-owned resource closure |

The lifecycle extension adds:

| Member | Barrier |
| --- | --- |
| `start()` | Return only after declared native intake resources are ready |
| `quiesce()` | Close native intake admission and cross the callback handoff fence |

The type boundary is available from the core facade:

```python
from tori_py_persistent_streams_core import (
    PersistentLog,
    PersistentStreamAdapter,
)
```

`PersistentStreamAdapter` extends the complete `PersistentLog`; it is not a
replacement containing only lifecycle methods.

## Factory Contract

The Tori Py integration injects the public runtime-checkable
`StreamAdapterFactory` Protocol as the canonical provider token:

```python
from dataclasses import dataclass

from tori_py_persistent_streams import StreamAdapterFactory
from tori_py_persistent_streams_core import PersistentStreamAdapter


@dataclass(frozen=True, slots=True)
class ExampleAdapterFactory:
    options: ExampleAdapterOptions

    def create(
        self,
        bindings: tuple[object, ...],
    ) -> PersistentStreamAdapter:
        return ExamplePersistentLog(self.options, bindings)


factory: StreamAdapterFactory = ExampleAdapterFactory(options)
```

The factory may return the adapter directly or return an awaitable. Construction
must not start native intake. Tori Py passes resolved immutable stream bindings;
the factory must not mutate them, discover controllers, or compile handler
pipelines.

An adapter module's `for_root()` and `for_root_async()` return `DeferredModule`
descriptors directly, provide `StreamAdapterFactory`, and export that same public
Protocol token. Options construction and descriptor materialization perform no
I/O.

## Responsibility Split

The adapter owns:

- Mapping logical streams and partitions to physical broker resources.
- Exact realization of the configured frozen partition router.
- Declaration or verification of inspectable topology.
- Encoding transport envelopes around core record fields when required.
- Native publication, confirms, and honest outcome classification.
- Native consumer ownership, start cursors, and serial partition delivery.
- Broker checkpoints or coordination with an explicit external store.
- Retention-gap detection supported by native facts.
- Capacity, deadlines, callbacks, reconnect generations, quiescence, and close.

The Tori Py integration owns:

- Controller discovery and handler compilation.
- Codec resolution and typed DTO decoding.
- Guards, pipes, interceptors, filters, and work scopes.
- Handler invocation and complete-success determination.
- Global cross-partition handler concurrency.
- Application publisher tokens, status, readiness, and shutdown drain.

An adapter must never invoke Tori Py handlers, resolve application scopes, or
checkpoint before the framework reports complete success.

## Start Capabilities

Advertise each mode independently:

```python
from tori_py_persistent_streams_core import StartModeCapabilities

CAPABILITIES = StartModeCapabilities(
    beginning=True,
    end=True,
    exact_offset=True,
    timestamp=False,
    relative_time=False,
)
```

Reject an unsupported mode before ownership or intake. Do not emulate an
unproven timestamp start with beginning, clamp an exact offset to a low
watermark, or recalculate end on every restart.

To support a mode, an adapter must persist an initialized inclusive cursor before
delivery. `End()` on an empty stream is supported only when that exact position
can survive restart without skipping the first later record.

## Routing and Topology

Use `StreamDefinition.router.route(partition_key, partition_count)` as the
authoritative selection. A native broker hash is valid only if it is the
configured router contract. Do not replace core SHA-256 with a driver's default
hash, Python `hash()`, or round robin.

Treat these as durable compatibility facts:

- Logical stream and physical partition naming.
- Partition count and partition-to-resource mapping.
- Router identity, compatibility key, and application key encoding.
- Named producer scope and producer names.
- Envelope version and header encoding.
- Cursor encoding and consumer-group identity.

Topology inspection must distinguish verified from unverified facts. If the
driver cannot inspect effective retention, policy, replication, placement, or
permissions, return or document those as operator preflight rather than claiming
verification.

## Publication Requirements

Route and validate before native allocation. Bound at least pending count,
pending bytes, confirmation waits, producer resources, and shutdown waits.

Map outcomes honestly:

- Return `CONFIRMED` only for the adapter's documented acceptance fact.
- Return `DEDUPLICATED` only when request identity and content equivalence are
  established for the named coordinate.
- Distinguish definitive rejection from timeout and indeterminate disconnect.
- Do not synthesize an offset from bounds, sequence numbers, or a subsequent
  read.
- Never automatically retry an accepted or indeterminate send.

If native sequence state survives restart but request-content association does
not, the adapter cannot claim an equivalent retry was deduplicated.

## Lease Requirements

One lease owns one `(stream, group, partition)` with an opaque generation token.
It must:

- Deliver strictly increasing offsets with gaps allowed.
- Reserve no more than one exact in-flight record.
- Reject a second fetch until the current delivery completes or is abandoned.
- Checkpoint only the exact delivered object.
- Fence callbacks and checkpoint completion by owner/resource generation.
- Wait for in-flight completion before ownership transfer or demotion.
- Stop on decode, ownership, checkpoint, or retention failure.
- Preserve cancellation and checkpoint uncertainty.

Finite callback queues alone are insufficient if the native driver can continue
buffering unbounded frames. Verify credit and every internal queue under a blocked
handler.

## Lifecycle Sequence

A lifecycle-complete adapter supports this Tori Py sequence:

```text
factory.create(resolved bindings)       no intake
-> declare_stream(...)                  prepare or verify topology
-> acquire(...) for every partition     prepare ownership resources
-> start()                              cross native readiness barrier
-> next_record/checkpoint/append        normal work
-> quiesce()                            close intake and callback handoff
-> close()                              release all resources
```

Partial startup failure must unwind every attempted resource. `close()` is
idempotent and observes all callback and cleanup tasks. A close callback from an
old resource generation must not mutate a replacement generation.

If transparent reconnect cannot re-run topology, ownership, cursor preparation,
and callback fencing, disable it and fail closed. Requiring a fresh adapter is
safer than replaying cached native subscriptions outside the contract.

## Core Conformance

The core package ships a public reusable suite:

```python
from tori_py_persistent_streams_core import PersistentLog
from tori_py_persistent_streams_core.testing import run_conformance_suite


async def isolated_log() -> PersistentLog:
    return await create_ready_isolated_log()


await run_conformance_suite(isolated_log)
```

Every factory call must return an isolated log over isolated test resources. The
portable suite covers declarations, routing, sparse ordering, starts, ownership,
both checkpoint strategies, concurrent cursor initialization, poison behavior,
named publishing, validation, cancellation, and close. Controlled retention is
capability-gated; portable behavior is not.

The suite expects a `PersistentLog` ready for its public operations. An adapter
whose required lifecycle ordering cannot be represented by the harness must not
claim core conformance merely because selected cases pass.

Run focused tests through `uv`:

```console
uv run pytest packages/tori-py-persistent-streams-core/tests
uv run pytest path/to/adapter/tests
```

## Tori Py Conformance

Separately test the configured factory and runtime for:

- Exactly one adapter provider and one application root.
- No I/O during options, descriptor, factory, or log construction.
- Handler and Protocol compilation before adapter I/O.
- Declaration and lease preparation before `start()`.
- Readiness only after the adapter barrier and partition task registration.
- Serial per-partition execution and bounded cross-partition pipeline work.
- Scope cleanup before checkpoint.
- Decode, pipeline, handler, cleanup, and checkpoint fail-stop behavior.
- Publication admission, adapter pressure, indeterminate outcomes, and close
  races.
- Quiesce callback fencing, admitted-work drain, deadline cancellation, and
  reverse resource close.

Infrastructure tests remain mandatory for durability, broker outages, failover,
retention, native buffering, TLS, permissions, and cluster placement. Neither
portable nor framework lifecycle conformance proves those facts.

The in-memory module is the reference composition, not a production adapter. The
RabbitMQ adapter is currently provisional and does not claim the complete core
and fault/cluster matrix; see [RabbitMQ](rabbitmq.md).

## Author Checklist

- Use only public core and Tori Py contracts.
- Freeze exact driver versions when compatibility depends on their API shape.
- Keep root import and option construction lazy and secret-safe.
- Publish immutable exact start capabilities.
- Preserve sparse offsets and both cursor tags.
- Prove no native clamp is hidden.
- Keep receipts offset-free.
- Bound messages, queues, credits, producers, tasks, waits, and diagnostics.
- Classify timeout, cancellation, disconnect, and NACK without inventing success.
- Fence old ownership and resource generations.
- Make retention gaps explicit and provide no automatic reset.
- Run core, Tori Py, and infrastructure suites as separate release gates.
