# nestpy-persistent-streams

`nestpy-persistent-streams` connects Nestpy modules and execution scopes to the
framework-neutral `persistent-streams` contracts. It does not contain a broker
driver and does not bridge CQRS events or `nestpy-microservices` handlers.

## Configuration

```python
from dataclasses import dataclass
from typing import Annotated, Protocol
from uuid import UUID

from nestpy import Inject, controller, module
from persistent_streams import PublishReceipt, StreamDefinition
from nestpy_persistent_streams import (
    ConfiguredStreamPublisher,
    PersistentStreamsModule,
    PersistentStreamsOptions,
    PersistentStreamsRuntimeOptions,
    PublisherRegistration,
    StreamBinding,
    StreamPayload,
    StreamPublisher,
    stream_handler,
    stream_publish,
    stream_publisher_token,
)
from nestpy_persistent_streams.testing import InMemoryPersistentStreamsModule


@dataclass(frozen=True)
class MemberUpdated:
    member_id: str


class JsonCodec:
    def encode(self, payload: object) -> bytes:
        assert isinstance(payload, MemberUpdated)
        return payload.member_id.encode()

    def decode(self, payload: bytes, target: type[object]) -> object:
        return target(payload.decode())


class MemberKey:
    def resolve(self, payload: object) -> bytes:
        assert isinstance(payload, MemberUpdated)
        return payload.member_id.encode()


class MemberPublisher(Protocol):
    @stream_publish(payload=MemberUpdated)
    async def updated(
        self,
        payload: MemberUpdated,
        *,
        record_id: UUID | None = None,
    ) -> PublishReceipt: ...


binding = StreamBinding(
    alias="member-activity",
    definition=StreamDefinition("member-activity-v1", 4),
    payload_type=MemberUpdated,
    codec=JsonCodec(),
    partition_key_resolver=MemberKey(),
)
streams = PersistentStreamsModule.for_root(
    PersistentStreamsOptions(
        bindings=(binding,),
        publishers=(
            PublisherRegistration("member-activity", protocol=MemberPublisher),
        ),
    ),
    imports=[InMemoryPersistentStreamsModule.for_root()],
)


@controller()
class Projection:
    @stream_handler(stream="member-activity", consumer_group="search-v1")
    async def apply(
        self,
        payload: Annotated[MemberUpdated, StreamPayload()],
    ) -> None:
        pass


@module(imports=[streams], controllers=[Projection])
class ApplicationModule:
    pass
```

The root is always global and composes adapter modules through normal Nestpy imports.
Use `StreamPublisher` for alias-selected publishing,
`Annotated[ConfiguredStreamPublisher[MemberUpdated],
Inject(stream_publisher_token("member-activity"))]` for a fixed named publisher,
or inject the explicit `MemberPublisher` Protocol token.

Injected configuration registers the application factory directly, so normal
annotations and `Annotated[..., Inject(token)]` dependencies work:

```python
streams = PersistentStreamsModule.for_root_async(
    bindings=(binding,),
    use_factory=create_runtime_options,
    imports=[InMemoryPersistentStreamsModule.for_root(), ConfigurationModule],
    publishers=(
        PublisherRegistration("member-activity", name="member-activity"),
        PublisherRegistration("member-activity", protocol=MemberPublisher),
    ),
)
```

`bindings` and `publishers` are always static because Nestpy must know provider
tokens while compiling the module graph. The injected factory returns only
`PersistentStreamsRuntimeOptions` (`owner_id`, its replica-uniqueness declaration,
single-instance consumer-group declaration, concurrency, poll interval,
`max_pending_publications`, and global pipeline) and is not called during
descriptor materialization. `max_pending_publications` is finite and defaults to
1024; admission above it raises `StreamPublicationSaturatedError` before adapter
I/O.

A complete broker-free application using all three publisher surfaces, typed
codec and pipe processing, partition metadata, checkpoints, and lifecycle
shutdown is available in the
[`examples/nestpy/persistent_streams`](../../examples/nestpy/persistent_streams/README.md)
directory.

## Delivery Contract

- Delivery and effects are at least once. Handlers must be idempotent.
- A record checkpoints only after decoding, the complete Nestpy pipeline, handler
  execution, interceptor unwind, and work-scope cleanup all succeed.
- Decode, validation, pipeline, handler, cleanup, and uncertain checkpoint
  failures stop that physical partition. Filters can observe an ordinary failure
  but cannot make it checkpoint eligible.
- Records remain serial within a partition. Cross-partition execution is bounded
  by `max_concurrency`.
- Retention gaps are startup or resumption failures; no offset is silently
  clamped. Operator recovery requires a compatible deployment, corrected source
  policy, or an explicit checkpoint reset.
- Shutdown atomically closes publication admission, asks the adapter to quiesce
  native intake, and then drains every admitted call. Cancellation during
  handler work leaves the record replayable; cancellation during checkpoint
  persistence blocks the partition with an unknown-outcome diagnostic. An
  adapter quiesce failure remains the primary error after admitted work drains.

An externally owned `CheckpointStore` is selected by putting an
`ExternalCheckpointStrategy` in the binding. Store fencing, compare-and-create,
and save uncertainty retain their `persistent-streams` meanings. The integration
never falls back to broker-managed checkpoints when an external store fails.

Broker-managed checkpoints are supported only in explicitly configured
single-instance deployments. A shared external checkpoint store supports
multi-replica deployments only when every replica uses a replica-unique owner ID
and the store provides atomic fence replacement and exact-owner save validation.

Blocked partitions are visible through `StreamRuntime.statuses` and make
`StreamRuntime.ready` false. Operators should preserve the failing offset while
deploying compatible decoding/handler code or applying an explicitly governed
source-data/checkpoint reset. Skipping a poison record is not an integration API.

## Adapter Authors

An adapter module provides and exports the public runtime-checkable
`StreamAdapterFactory` Protocol class as its canonical Nestpy token. Its
`for_root()` and `for_root_async()` methods return a `DeferredModule` directly.
The factory receives resolved immutable bindings and
returns a public `persistent_streams.PersistentStreamAdapter`. Its `start()`
must cross the native readiness barrier and its `quiesce()` must close intake
and callback handoff before returning. It must preserve exact
partition routing, start cursor, ownership, checkpoint uncertainty, publication
outcomes, and close semantics. It must not discover Nestpy controllers or invoke
handler pipelines.

Run core `PersistentLog` conformance against the log implementation, then run
the Nestpy package lifecycle/execution tests against the configured adapter.
Passing one suite does not replace the other. The in-memory module under
`nestpy_persistent_streams.testing` is the reference composition, not a durable
production adapter.

Adapters implement `StreamAdapterFactory` and return a public
`PersistentStreamAdapter`; bare `PersistentLog` implementations remain the core
conformance boundary but are not lifecycle-complete Nestpy adapters.
Core `PersistentLog` conformance and Nestpy lifecycle tests remain separate.
