# Handlers and Publishers

`tori-py-persistent-streams` connects the portable log contract to Tori Py
modules, dependency injection, controller discovery, work scopes, pipelines,
application lifecycle, and typed publishers. It contains no broker driver.

```console
uv add tori-py-persistent-streams
```

Use one always-global `PersistentStreamsModule` root and import exactly one
adapter module into that root.

## Configure a Binding

A binding joins an application alias to its physical stream definition, payload
type, codec, partition-key resolver, start, and checkpoint policy:

```python
import json
from dataclasses import dataclass

from tori_py_persistent_streams import (
    PersistentStreamsModule,
    PersistentStreamsOptions,
    PersistentStreamsRuntimeOptions,
    StreamBinding,
)
from tori_py_persistent_streams.testing import InMemoryPersistentStreamsModule
from tori_py_persistent_streams_core import Beginning, StreamDefinition


@dataclass(frozen=True, slots=True)
class MemberUpdated:
    member_id: str
    display_name: str


class MemberUpdatedCodec:
    def encode(self, payload: MemberUpdated) -> bytes:
        return json.dumps(
            {
                "member_id": payload.member_id,
                "display_name": payload.display_name,
            },
            separators=(",", ":"),
        ).encode()

    def decode(
        self,
        payload: bytes,
        target: type[MemberUpdated],
    ) -> MemberUpdated:
        del target
        value = json.loads(payload)
        return MemberUpdated(value["member_id"], value["display_name"])


class MemberPartitionKey:
    def resolve(self, payload: MemberUpdated) -> bytes:
        return payload.member_id.encode()


member_activity = StreamBinding[MemberUpdated](
    alias="member-activity",
    definition=StreamDefinition("member-activity-v1", partition_count=8),
    payload_type=MemberUpdated,
    codec=MemberUpdatedCodec(),
    partition_key_resolver=MemberPartitionKey(),
    start=Beginning(),
)

streams = PersistentStreamsModule.for_root(
    PersistentStreamsOptions(
        bindings=(member_activity,),
        runtime=PersistentStreamsRuntimeOptions(
            owner_id="projection-replica-a",
            max_concurrency=16,
            poll_interval=0.01,
            max_pending_publications=1024,
        ),
    ),
    imports=[InMemoryPersistentStreamsModule.for_root()],
)
```

The alias is the application-facing identity used by handlers and publishers.
Aliases and consumer groups use lowercase ASCII
`[a-z][a-z0-9_-]{0,62}`. The `StreamDefinition.name` is the adapter-facing logical
stream identity and need not equal the alias.

Configuration is immutable before startup. A publication cannot override the
codec, payload type, partition-key resolver, router, partition count, physical
stream, producer identity, or publishing-ID source.

Codec, resolver, and publishing-ID components may be instances or normal Tori Py
provider tokens. Provider tokens are resolved from the root's imports before the
adapter is created. They must resolve to singleton instances implementing the
corresponding public protocols.

## Configure Runtime Options Asynchronously

Bindings and publisher registrations are static because they create DI tokens.
An injected factory may supply runtime-only values:

```python
from typing import Annotated

from tori_py import Inject
from tori_py_persistent_streams import (
    PersistentStreamsModule,
    PersistentStreamsRuntimeOptions,
)


async def stream_runtime_options(
    replica: Annotated[str, Inject("settings:replica-id")],
) -> PersistentStreamsRuntimeOptions:
    return PersistentStreamsRuntimeOptions(
        owner_id=replica,
        owner_id_is_replica_unique=True,
        max_concurrency=32,
        max_pending_publications=2048,
    )


streams = PersistentStreamsModule.for_root_async(
    bindings=(member_activity,),
    use_factory=stream_runtime_options,
    imports=[adapter_module, configuration_module],
)
```

The factory is registered directly with Tori Py, may be synchronous or
asynchronous, and is not called during import or deferred-module materialization.
It must return `PersistentStreamsRuntimeOptions`, not a replacement static
inventory.

An application may configure only one persistent-stream root. Missing and
competing adapter imports fail through normal Tori Py provider resolution.

## Declare a Handler

Handlers are direct async methods on explicitly registered Tori Py controllers:

```python
from collections.abc import Mapping
from typing import Annotated

from tori_py import controller
from tori_py_persistent_streams import (
    StreamContext,
    StreamHeader,
    StreamHeaders,
    StreamOffset,
    StreamPartition,
    StreamPayload,
    StreamRecordContext,
    stream_handler,
)


@controller()
class MemberProjection:
    @stream_handler(
        stream="member-activity",
        consumer_group="member-card-v1",
    )
    async def apply(
        self,
        payload: Annotated[MemberUpdated, StreamPayload()],
        context: Annotated[StreamContext, StreamRecordContext()],
        headers: Annotated[Mapping[str, bytes], StreamHeaders()],
        partition: Annotated[int, StreamPartition()],
        offset: Annotated[int, StreamOffset()],
        trace_id: Annotated[bytes | None, StreamHeader("trace-id")] = None,
    ) -> None:
        await update_member_card(
            payload,
            record_id=context.record_id,
            partition=partition,
            offset=offset,
            trace_id=trace_id,
        )
```

Compilation happens after the final application graph and testing overrides are
known, but before adapter I/O. The compiler uses Tori Py `DiscoveryService` and
examines only methods directly declared in each controller's `__dict__`.
Inherited decorated methods are not discovered.

Handler rules are intentionally strict:

- The method is async and explicitly returns `None`.
- Every non-`self` parameter has exactly one supported stream marker.
- Exactly one parameter is marked `StreamPayload()`.
- The payload annotation is exactly the binding's configured payload type.
- Variadic parameters and unresolved annotations are rejected.
- Each `(stream alias, consumer group)` has one handler application-wide.
- The referenced alias must exist.

Use a separate stable consumer group for each independent effect. Combining two
independent effects in one handler couples both to one checkpoint. Registering
two handlers with the same alias and group is rejected rather than creating an
ambiguous checkpoint boundary.

### Inject Work-Scoped Providers

`StreamInject` resolves a normal provider from the exact module that owns the
handler:

```python
from typing import Annotated

from tori_py_persistent_streams import StreamInject, StreamPayload


async def apply(
    self,
    payload: Annotated[MemberUpdated, StreamPayload()],
    repository: Annotated[MemberRepository, StreamInject(MemberRepository)],
) -> None:
    await repository.apply(payload)
```

Each record attempt runs in a fresh Tori Py work scope. Request-scoped resources
are finalized before the checkpoint. A cleanup failure blocks the partition and
leaves the record ineligible for checkpointing.

`StreamContext` provides application, owner module, handler, alias, group,
partition, offset, broker timestamp, record UUID, immutable headers, and the
scoped resolver. Its `execution_kind` is `"stream"`. `unwrap()` exposes only the
adapter-provided native value; application handlers cannot use it to checkpoint,
change credit, mutate topology, or own a connection.

## Pipeline Order

The integration reuses Tori Py's transport-neutral guards, pipes, interceptors,
filters, and work scopes. It does not reuse HTTP or microservices executors.

One attempt executes in this order:

```text
bounded codec decode to the declared DTO
-> open a fresh exact-owner work scope
-> global guards, controller guards, method guards
-> bind arguments
-> global pipes, controller pipes, method pipes
-> global interceptors, controller interceptors, method interceptors
-> handler
-> interceptor unwind in reverse order
-> close and finalize the work scope
-> checkpoint outside the closed work scope
```

Pipes run for payload, header, headers, partition, and offset parameters. Context
and injected provider parameters are not piped. Provider-backed pipeline
components resolve lazily from the handler-owner scope; direct component
instances remain externally owned.

If decode, DTO validation, a guard, pipe, interceptor, handler, or cleanup fails,
the physical partition stops at that offset. Exception filters are notified of
ordinary invocation failures, but their return value cannot recover the attempt
or make it checkpoint eligible. A failing filter also cannot replace the primary
record failure.

Records remain serial within one physical partition. `max_concurrency` bounds
simultaneous pipeline and handler execution across partitions; it does not create
parallelism inside a partition.

## Publish Through the Raw Surface

The global `StreamPublisher` selects an already configured alias:

```python
from tori_py_persistent_streams import StreamPublisher


class MemberService:
    def __init__(self, streams: StreamPublisher) -> None:
        self._streams = streams

    async def update(self, update: MemberUpdated) -> None:
        receipt = await self._streams.publish(
            "member-activity",
            update,
            headers={"schema": b"member-updated-v1"},
        )
        record_publish_outcome(receipt)
```

The alias must exist and the payload must be an instance of the binding's payload
type. The publisher generates a UUID only when `record_id` is omitted. Pass an
explicit UUID when the application must retain retry identity.

The raw publisher is not an encoded-byte or native-driver escape hatch. It cannot
select arbitrary physical stream names or native publish options.

## Publish Through a Configured Token

Every binding automatically exports a fixed publisher token for its alias:

```python
from typing import Annotated

from tori_py import Inject
from tori_py_persistent_streams import (
    ConfiguredStreamPublisher,
    stream_publisher_token,
)


class MemberService:
    def __init__(
        self,
        publisher: Annotated[
            ConfiguredStreamPublisher[MemberUpdated],
            Inject(stream_publisher_token("member-activity")),
        ],
    ) -> None:
        self._publisher = publisher

    async def update(self, update: MemberUpdated) -> None:
        await self._publisher.publish(update)
```

Register an additional application-facing name when the alias is not the desired
DI vocabulary:

```python
from tori_py_persistent_streams import PublisherRegistration

registration = PublisherRegistration(
    stream="member-activity",
    name="member-updates",
)
```

Inject it with `stream_publisher_token("member-updates")`. Explicit publisher
names may not collide with binding aliases or another publisher name.

## Publish Through a Protocol

An explicit `typing.Protocol` provides a domain-oriented method name without
inferring a stream or schema from that name:

```python
from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from tori_py_persistent_streams import (
    PublisherRegistration,
    stream_publish,
)
from tori_py_persistent_streams_core import PublishReceipt


class MemberActivityPublisher(Protocol):
    @stream_publish(payload=MemberUpdated)
    async def member_updated(
        self,
        payload: MemberUpdated,
        *,
        record_id: UUID | None = None,
        headers: Mapping[str, bytes] | None = None,
    ) -> PublishReceipt: ...


registration = PublisherRegistration(
    stream="member-activity",
    name="member-updates",
    protocol=MemberActivityPublisher,
)
```

The root registers a dynamic proxy under `MemberActivityPublisher`. Every
non-dunder Protocol method must:

- Be async and decorated with `@stream_publish(payload=...)`.
- Declare the configured payload type as a required parameter without a default.
- Declare keyword-only `record_id: UUID | None = None`.
- Optionally declare keyword-only `headers` with a `None` default.
- Return `PublishReceipt`.

The proxy uses normal Python signature binding and delegates to the same fixed
configured publisher as the other two surfaces. It does not generate classes,
dispatch CQRS events, or infer routing from a method name.

## Configure Named Publishing

Named producer policy belongs to the binding, not a publication call:

```python
from uuid import UUID


class StablePublishingIds:
    def next_id(self, record_id: UUID, partition_key: bytes) -> int:
        return durable_id_registry.id_for(record_id, partition_key)


member_activity = StreamBinding[MemberUpdated](
    alias="member-activity",
    definition=StreamDefinition("member-activity-v1", 8),
    payload_type=MemberUpdated,
    codec=MemberUpdatedCodec(),
    partition_key_resolver=MemberPartitionKey(),
    producer_name="member-api-v1",
    publishing_id_source=StablePublishingIds(),
)
```

Both `producer_name` and `publishing_id_source` are required for named mode. The
source receives the record UUID and partition key. It must return an ID that is
stable for an exact retry and monotonic for each routed physical producer
coordinate. A process-local counter is not a cross-restart retry strategy.

## Interpret Publication Outcomes

All surfaces return the same `PublishReceipt`. Portable outcomes include:

| Outcome | Interpretation |
| --- | --- |
| `CONFIRMED` | Adapter documented acceptance |
| `DEDUPLICATED` | Exact named coordinate was already accepted |
| `REJECTED` | Adapter definitively rejected publication |
| `TIMED_OUT` | Deadline expired; acceptance can be indeterminate |
| `CLOSED` | Adapter was closed |
| `BACKPRESSURED` | Adapter capacity rejected local admission |
| `INDETERMINATE` | Acceptance cannot be proven either way |

Not every adapter emits every enum value. Inspect the adapter's documented
mapping. Never automatically resend a timed-out or indeterminate publication.
An intentional exact retry needs the same record UUID and the same named producer
coordinate and publishing ID. Reusing only the UUID in unnamed mode does not
provide append deduplication.

## Admission and Backpressure

There are two independent capacity boundaries:

1. `PersistentStreamsRuntimeOptions.max_pending_publications` bounds calls
   admitted into the Tori Py runtime. The default is 1,024. Exceeding it raises
   `StreamPublicationSaturatedError` before adapter I/O.
2. An adapter can enforce its own pending count, pending bytes, confirm, or native
   resource limits. It may return `PublishOutcome.BACKPRESSURED` or raise a typed
   adapter resource error according to its public contract.

Do not catch saturation and immediately spin. Bound the caller's queue, apply a
finite deadline, reduce ingress, and expose pressure as an operational signal.

Publication admission is closed before quiescence begins. Calls already admitted
are observed and drained against the application shutdown deadline. Calls arriving
after the fence raise `StreamRuntimeError` without adapter I/O.

## Readiness and Status

Inject `StreamRuntime` to expose lifecycle and bounded per-partition status:

```python
from tori_py_persistent_streams import StreamRuntime


def stream_health(runtime: StreamRuntime) -> dict[str, object]:
    return {
        "ready": runtime.ready,
        "state": runtime.state.value,
        "partitions": runtime.statuses,
    }
```

Runtime states are `created`, `prepared`, `running`, `degraded`, `quiescing`, and
`closed`. Startup performs these barriers:

1. Compile handlers and publisher Protocols.
2. Resolve codecs, resolvers, ID sources, and the adapter factory.
3. Create the adapter and declare each stream.
4. Acquire every handler's partition lease without opening native intake.
5. Await `adapter.start()` readiness during application bootstrap.
6. Start one task per handler partition and wait for each task to enter intake.
7. Publish `running` only after the barrier completes.

`runtime.ready` is true only while state is `running` and no status is blocked. A
decode, handler, checkpoint, intake, or stopped-lease failure marks the affected
partition `blocked`, changes runtime state to `degraded`, and makes readiness
false. Other partition tasks can continue, so liveness and readiness must not be
treated as the same signal.

For a running status, `offset` is the last successfully checkpointed record seen
by the runtime. For a blocked status, it identifies the failing or uncertain
record when known. Interpret it together with `state` and `diagnostic_code`.

There is no hot skip or resume API for a blocked partition. Preserve its
coordinates, correct the cause, and restart or replace the application according
to the [operations guide](operations.md).

## Shutdown

Normal application quiescence:

1. Atomically closes publisher and consumer admission.
2. Awaits the adapter's native-intake and callback-handoff fence.
3. Drains admitted handler and publication tasks within the shared deadline.
4. Lets successful work scopes finish before checkpointing.
5. Cancels remaining work at the deadline.
6. Releases leases and closes adapter resources.

Cancellation during handler work leaves the record replayable. Cancellation
during checkpoint persistence has an unknown outcome and blocks the partition
with `tori_py_persistent_streams.checkpoint_outcome_unknown`. If adapter quiesce
fails, admitted work is still drained and the quiesce error remains primary.

Run the executable example and integration tests with `uv`:

```console
uv run python -m examples.tori_py.persistent_streams.app
uv run pytest examples/tori_py/persistent_streams
uv run pytest packages/tori-py-persistent-streams/tests
```
