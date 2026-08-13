# ToriPy Persistent Streams Architecture

## 1. Status and Purpose

This document defines the accepted architecture for the optional
`tori-py-persistent-streams` integration. It connects the framework-neutral
`tori-py-persistent-streams-core` contracts to ToriPy modules, discovery, dependency
injection, pipelines, work scopes, lifecycle, and shutdown.

Implementation order is governed by
[`TORI_PY_PERSISTENT_STREAMS_IMPLEMENTATION_PLAN.md`](TORI_PY_PERSISTENT_STREAMS_IMPLEMENTATION_PLAN.md).
Executable phase contracts live under `spec/tori-py-persistent-streams/`.

The integration provides:

- one application-wide persistent-stream runtime configured by a global root;
- adapter composition without broker knowledge in this package;
- global discovery of explicitly registered `@stream_handler` controllers;
- typed DTO decoding through a configured stream codec;
- normal ToriPy guards, pipes, interceptors, filters, and work scopes;
- checkpoint advancement only after successful work-scope finalization;
- raw, named configured, and Protocol-token publisher injection;
- bounded startup, intake, reconnect handoff, quiescence, and shutdown.

Persistent streams are replayable partitioned logs. They are not RPC, queue
events, a CQRS event bus, or an event store.

## 2. Package Boundary

```text
tori-py-persistent-streams
  -> tori_py
  -> tori-py-persistent-streams-core

adapter distribution
  -> tori-py-persistent-streams-core
  -> tori-py-persistent-streams
  -> native broker driver
```

`tori_py` and `tori-py-persistent-streams-core` MUST NOT import this integration. This package
MUST NOT import RabbitMQ, `rstream`, `tori-py-microservices`, CQRS, event
sourcing, SQLAlchemy, Starlette, Alembic, or application modules.

The framework-neutral package owns stream identities, opaque records, offsets,
configured deterministic routing, resume cursors, log protocols, publication
semantics, and `PersistentLog` conformance. This integration owns codecs, typed DTO
contracts, ToriPy composition, and ToriPy execution.

## 3. Terminology

- **Logical stream**: one configured append-only log exposed to application
  code. It can map to one physical stream or a partitioned broker construct.
- **Physical partition**: one ordered append-only log within a logical stream.
- **Stream binding**: immutable application configuration joining one logical
  stream to its codec, partition-key resolver, producer identity, publishing-ID
  source, and adapter.
- **Consumer group**: stable processing identity that owns one checkpoint per
  physical partition.
- **Resume cursor**: an initialized inclusive start cursor or the last
  successfully processed physical offset.
- **Delivery attempt**: one framework invocation for one record at one offset.
- **Configured publisher**: a publisher whose stream binding and payload
  contract are fixed before application bootstrap.
- **Raw publisher**: the global application-facing publisher that selects an
  already configured binding explicitly. It is not a native-driver escape hatch.

## 4. Root Composition

The application creates one root and imports it once:

```python
rabbitmq = RabbitMqPersistentStreamsModule.for_root(
    RabbitMqPersistentStreamsOptions(...)
)

streams = PersistentStreamsModule.for_root(
    PersistentStreamsOptions(
        bindings=(member_activity_binding,),
    ),
    imports=[rabbitmq],
)


@module(imports=[streams, MembersModule, ProjectionsModule])
class AppModule:
    pass
```

`RabbitMqPersistentStreamsModule.for_root()` returns a `DeferredModule` that
provides and exports the public runtime-checkable `StreamAdapterFactory` Protocol
class as its canonical ToriPy token. `PersistentStreamsModule` receives that
descriptor in its normal `imports`, directly injects `StreamAdapterFactory`, and
exports application-facing stream providers.

This is standard Nest-style module composition. A missing adapter produces
`provider.unresolved`; two distinct imported adapter module classes exporting
the same token produce `provider.ambiguous`. No process-global adapter registry
or adapter-specific token wrapper is needed.

The root is always `global_=True`. There is no `global_` argument, public root
`key`, or local root mode. A second `PersistentStreamsModule` root in one
application is a bootstrap error. The single root may contain several
distinct stream bindings.

## 5. Synchronous and Injected Configuration

```python
class PersistentStreamsModule:
    @classmethod
    def for_root(
        cls,
        options: PersistentStreamsOptions,
        *,
        imports: Iterable[ModuleImport] = (),
    ) -> DeferredModule: ...

    @classmethod
    def for_root_async(
        cls,
        *,
        bindings: Iterable[StreamBinding],
        publishers: Iterable[PublisherRegistration] = (),
        use_factory: PersistentStreamsRuntimeOptionsFactory,
        imports: Iterable[ModuleImport] = (),
    ) -> DeferredModule: ...
```

`for_root_async()` takes bindings and publisher registrations as static
structural inventory, then registers `use_factory` directly as a singleton
ToriPy provider for `PersistentStreamsRuntimeOptions`. The factory may be
synchronous or asynchronous and returns only owner identity, concurrency, poll
interval, finite pending-publication capacity, and global pipeline settings.
Dependencies come only from annotations and `Annotated[..., Inject(token)]`;
there is no parallel `inject=[]` API and the descriptor does not invoke the
factory during materialization. Runtime factory output cannot add DI tokens or
duplicate the static publisher inventory. Static inventory validation does not
construct placeholder runtime settings; owner limits are checked against the
resolved factory result.

The async root's explicit `imports` serve both adapter composition and runtime
options-factory dependencies. Adapter configuration is separate and may provide
its own annotation-driven async factory API; an adapter's async imports remain
local to resolving that adapter's options factory.

## 6. Immutable Stream Bindings

Every binding fixes before intake opens:

- stable logical stream identity and application alias;
- exact `StreamCodec` instance or provider token;
- exact partition-key resolver instance or provider token;
- configured deterministic router and version frozen for the stream;
- optional named-producer identity and publishing-ID source; unnamed mode is a
  complete supported configuration and requires neither;
- configured payload size and metadata limits;
- named publisher aliases and optional publisher Protocol contracts;
- consumer start and checkpoint policy defaults allowed by the adapter.

No publication call may replace the codec, resolver, producer identity,
publishing-ID source, physical stream, or partition count. Those are deployment
and compatibility contracts, not per-message options.

The resolver derives stable bytes from the typed DTO. It does not select a
partition. The binding's frozen `PartitionRouter` selects the partition; core's
versioned SHA-256 router is the default, not a mandatory adapter algorithm.

Logical aliases and consumer-group names use lowercase ASCII
`[a-z][a-z0-9_-]{0,62}`. Duplicates, conflicting Protocol tokens, duplicate
named publishers, and references to unknown bindings fail before adapter I/O.

Bindings, options, compiled plans, metadata, and provider maps are immutable and
defensively copied. Secrets and native connections never appear in them.

## 7. Handler Metadata and Discovery

Handlers are ordinary methods on explicitly registered ToriPy controllers:

```python
@controller()
class MemberActivityProjection:
    @stream_handler(
        stream="member-activity",
        consumer_group="profile-search-v1",
    )
    async def apply(
        self,
        record: Annotated[MemberActivityV1, StreamPayload()],
        context: Annotated[StreamContext, StreamRecordContext()],
    ) -> None:
        ...
```

`@stream_handler` stores direct immutable mapping metadata only. It does not
register the method globally, import a module, open a consumer, or select a
native driver.

During singleton startup the compiler injects `DiscoveryService`, calls
`get_controllers()` after the final graph and testing overrides exist, and
examines methods directly declared in each controller `__dict__`. There is no
package scan, subclass scan, inherited handler publication, endpoint module,
handler list, or mutable registry.

The application has at most one handler for each `(stream, consumer_group)`.
This avoids coupling several effects to one checkpoint. Two independent effects
use two stable groups and therefore independent replay positions.

Each compiled plan retains exact owner `ModuleId`, controller `ProviderRef`,
method, stream binding, consumer group, payload annotation, parameter bindings,
pipeline bindings, and deterministic diagnostic identity.

## 8. Stream-Specific Parameter Markers

The package defines its own markers:

- `StreamPayload()` for the complete typed DTO;
- `StreamRecordContext()` for transport-neutral record context;
- `StreamHeaders()` and `StreamHeader(name)` for safe immutable metadata;
- `StreamPartition()` and `StreamOffset()` for physical position facts;
- `StreamInject(token)` for normal ToriPy provider resolution.

These markers and `@stream_handler` are independent of
`tori-py-microservices`. Neither package imports, aliases, recognizes, or
silently accepts the other package's payload, context, header, or handler
metadata.

Every non-`self` parameter has exactly one supported marker. Variadic
parameters, more than one complete payload, unresolved annotations, synchronous
handlers, and return annotations other than explicit `None` fail startup.

## 9. Codec and Typed Payload Contract

The adapter supplies an encoded record with logical stream, physical partition,
offset, timestamp, headers, partition key, and bytes. The configured
`StreamCodec` performs bounded structural decoding and constructs the handler's
declared payload DTO. The framework never passes native `rstream` messages to
ordinary handlers.

Codec decoding happens before handler invocation but under the partition
runtime's failure boundary. A malformed record, unsupported schema, oversized
record, or DTO construction failure stops that physical partition. It does not
advance the checkpoint, skip the record, send it to a queue, or continue with a
later offset. Other partitions may continue, but application readiness is
degraded and diagnostics identify the blocked position.

This fail-stop rule is deliberate: a persistent log has no universal reject or
dead-letter settlement, and skipping would silently make replay state diverge.
Recovery requires a compatible deployment, corrected source data under an
application-owned migration policy, or an explicit operator reset.

## 10. Invocation Pipeline

Each decoded record executes through one fresh exact-owner ToriPy work scope:

```text
decode typed DTO
-> work_scopes.run_in(owner_module,
     filter boundary(
       global/controller/handler guards
       -> bind arguments
       -> global/controller/handler pipes
       -> global/controller/handler interceptors
       -> handler
     )
   )
-> successful scope cleanup
-> checkpoint
```

The integration reuses ToriPy's transport-neutral `Guard`, `Pipe`,
`Interceptor`, `ExceptionFilter`, `ArgumentMetadata`, and pipeline metadata. It
does not reuse HTTP or microservices executors. HTTP middleware and
microservices enhancer registries are not applied.

Provider-backed pipeline components resolve from the handler owner's work
scope. Direct instances remain externally owned. Interceptor `next` callbacks
are one-shot. Filters catch ordinary exceptions but never process-control or
cancellation values.

`StreamContext.execution_kind == "stream"`. It exposes immutable stream,
partition, offset, timestamp, consumer-group, headers, correlation metadata,
handler identity, and scoped resolver. Its scope lease is invalid after the
attempt. A typed read-only `unwrap()` may expose native context; it does not
allow checkpoint, unsubscribe, connection, credit, or topology mutation.

## 11. Ordering, Concurrency, and Failure

Records execute serially within each physical partition. Different partitions
may execute concurrently up to the root's finite concurrency bound. The runtime
never starts a later delivered offset before the current record has completed
and its cursor outcome is definitive; adjacent offsets are not assumed.

An ordinary handler or pipeline failure leaves the checkpoint unchanged, stops
the partition immediately, and degrades readiness. Reacquiring or restarting the
partition redelivers the same record. There is no automatic retry loop, delay,
dead letter, or skip. Filters may map an error for diagnostics, but no filter can
convert any decode, pipeline, handler, or cleanup failure into cursor eligibility.

Delivery and execution are at least once. Handlers must tolerate duplicates.
The integration does not claim atomicity between application side effects and a
broker or external checkpoint store.

## 12. Checkpoint Boundary

A checkpoint can advance only after all of these succeed:

1. codec decode and typed DTO construction;
2. guards, pipes, interceptors, and handler body;
3. interceptor unwind;
4. work-scope resource finalization;
5. checkpoint persistence itself.

The canonical `ResumeCursor` is either an initialized inclusive start cursor or
the last successfully processed offset. Adapters preserve that distinction and
reject unsupported start/checkpoint combinations before intake.

A process crash after effects commit but before checkpoint persistence causes
duplicate execution. A checkpoint write with an indeterminate outcome stops the
partition; it is never guessed successful. On recovery, reading either the old
or new checkpoint remains safe only when the handler is idempotent.

Checkpoint store/query timeout, cancellation, or disconnect has an unknown
persistence outcome unless the adapter first returns or raises a definitive
result; recovery may observe either the old or new cursor. The runtime
tracks the checkpoint phase, stops and blocks that partition with a bounded
unknown-outcome diagnostic, and still propagates `CancelledError` for shutdown.

Broker checkpoints and externally supplied `CheckpointStore` implementations
are both supported by the adapter contract. External stores remain
application-owned resources and can use normal ToriPy DI. The runtime does not
silently fall back from an unavailable external store to broker checkpoints.

Broker-managed checkpoints are supported only in explicitly configured
single-instance deployments. A shared external checkpoint store supports
multi-replica deployments only when every replica uses a replica-unique owner ID
and the store provides atomic fence replacement and exact-owner save validation.

If retention has removed the checkpointed offset, startup or resumption fails
with a checkpoint-expired diagnostic. Silent broker clamping to the first
available offset is prohibited.

## 13. Publisher APIs

### 13.1 Global raw publisher

The global root exports one `StreamPublisher` singleton:

```python
await publisher.publish(
    "member-activity",
    MemberProfileUpdatedV1(...),
    record_id=retry_record_id,
)
```

The alias selects an existing binding. The publisher uses that binding's codec,
partition resolver, router, and optional named-producer policy. It generates a
UUID when `record_id` is omitted; callers may provide one for retry reuse. It cannot
publish to an arbitrary native stream or accept encoded bytes as an untyped
shortcut.

### 13.2 Named configured publishers

A binding may export a narrow publisher under a deterministic named token:

```python
publisher: Annotated[
    ConfiguredStreamPublisher[MemberActivityV1],
    Inject(stream_publisher_token("member-activity")),
]
```

Its API omits the stream alias and validates the declared payload contract.
Names are unique application-wide.

### 13.3 Protocol-token publishers

Applications may register an explicit `typing.Protocol` as a binding token:

```python
class MemberActivityPublisher(Protocol):
    @stream_publish(payload=MemberProfileUpdatedV1)
    async def profile_updated(
        self,
        payload: MemberProfileUpdatedV1,
        *,
        record_id: UUID | None = None,
    ) -> PublishReceipt:
        ...
```

The compiler validates async signatures and explicit method metadata before
startup and registers one dynamic proxy under the Protocol token. The proxy
uses normal Python argument binding and delegates to the same configured
publisher. It does not generate classes, infer schemas, dispatch CQRS events,
or choose a stream from a Python method name. Payload parameters cannot declare
defaults.

All three APIs accept optional explicit `record_id` and return a `PublishReceipt`
whose typed outcome distinguishes confirmed, rejected, timed-out, closed,
backpressured, and indeterminate publication. Confirmation means
adapter-defined broker acceptance, not handler execution. A receipt contains the
record UUID, selected partition, and confirmation facts, never a broker offset or
`StoredRecord`. No accepted or indeterminate call is retried automatically;
exact indeterminate retry requires caller reuse of `record_id` and the same
producer coordinate/handle.

## 14. Adapter Contract

Each adapter module provides and exports the public runtime-checkable
`StreamAdapterFactory` Protocol class itself as the canonical provider token.
Its configuration methods return `DeferredModule` directly. The factory creates
an application-owned `PersistentStreamAdapter` from immutable
compiled bindings. The ToriPy runtime supplies each compiled handler as the
framework-neutral consumer runner's record callback. The adapter:

- maps logical streams to physical partitions;
- prepares or verifies topology;
- publishes encoded records and reports confirms;
- starts partition consumers at exact checkpoints;
- persists broker checkpoints or coordinates explicit external checkpoint
  stores through the framework-neutral contracts;
- reports partition assignment, status, and failures;
- stops intake and closes native resources.

The lifecycle extension retains the complete `PersistentLog` API and adds
`start()` and `quiesce()` barriers. `start()` returns only after native intake is
ready. `quiesce()` closes native intake admission and crosses its callback
handoff fence before framework task draining begins.

It never discovers controllers, resolves handlers, decodes DTOs, executes
ToriPy pipelines, owns work scopes, or advances a checkpoint before the
framework completion callback reports success.

## 15. Lifecycle and Shutdown

Startup order is:

1. compile the ToriPy graph and enforce one global stream root;
2. construct singleton providers and controllers;
3. resolve options and adapter factory without opening intake;
4. discover and compile every stream handler;
5. validate bindings, publishers, groups, checkpoints, and signatures;
6. acquire adapter resources and prepare or verify streams;
7. query checkpoints and build partition assignments;
8. open ToriPy work-scope admission;
9. await `adapter.start()` in `on_application_bootstrap()`;
10. start partition tasks and require each to signal intake entry or fail;
11. publish `RUNNING` only after the exact readiness barrier completes.

Any failure unwinds acquired resources in reverse order and prevents readiness.

Quiescence closes publisher and consumer admission first, stops new adapter
callbacks, crosses the adapter callback-handoff fence, and drains accepted
record/publication tasks against `ShutdownContext.remaining()`. Work scopes
finish before final checkpoints. Deadline cancellation leaves uncheckpointed
records replayable. Resource shutdown never starts detached cleanup after the
shared deadline.

## 16. Observability and Security

Bounded status and diagnostics include logical stream, physical partition,
consumer group, offset bucket, handler ID, producer identity, publishing ID,
attempt, lag, checkpoint class, confirm latency, and lifecycle state. Payloads,
member identifiers, handles, content, credentials, and raw headers are not
metric labels or default logs.

Headers are immutable, allowlisted, and size-limited. Trace context may be
propagated explicitly. Stream identity, partition routing, and broker metadata
are never authorization facts; guards or application services own authorization.

Native adapter credentials and TLS policy remain adapter concerns. The ToriPy
integration redacts adapter options and errors crossing its diagnostics boundary.

## 17. CQRS and Microservices Boundaries

There is no `EventHandler`, `EventDispatcher`, command bus, query bus, or domain
event bridge. The package does not subscribe CQRS handlers to streams and does
not publish CQRS, domain, or event-sourced events automatically.

An explicit stream handler may translate a validated DTO into an in-process
command or application service call. An application may publish from an outbox
relay. Those are visible application boundaries with their own idempotency and
transaction policy.

`tori-py-microservices` remains responsible for RPC and queue-event semantics.
Its decorators, contexts, publishers, codecs, settlement, and RabbitMQ
connections are not reused. Deployments may use both packages in one
application, but their roots and lifecycles remain independent.

## 18. Testing Strategy

Package tests cover:

- exact root composition and mandatory global behavior;
- annotation-driven sync/async factories;
- global direct-method discovery and duplicate diagnostics;
- marker and signature compilation independent of microservices;
- typed codec failures and partition fail-stop behavior;
- exact pipeline order and module-qualified work scopes;
- cleanup-before-checkpoint and checkpoint uncertainty;
- serial per-partition and bounded cross-partition concurrency;
- raw, named, and Protocol publisher injection;
- startup rollback, callback fencing, quiescence, and forced shutdown;
- framework-neutral conformance with the in-memory reference and adapter fakes;
- exact public API, import boundaries, wheel, and sdist artifacts.

Concrete logs run core `PersistentLog` conformance. ToriPy adapters separately
run lifecycle/execution conformance for topology preparation, callback handoff,
pipeline completion, cursor persistence, readiness, and shutdown, plus their
infrastructure tests. Passing one suite does not imply passing the other.

## 19. Explicit Non-Goals

The first implementation does not provide:

- an event-handler or `EventDispatcher` bridge;
- RPC, request-response, queue settlement, dead letters, or poison skipping;
- automatic CQRS, domain-event, or event-sourcing integration;
- exactly-once processing or distributed transactions;
- package scanning, inherited handlers, or endpoint modules;
- arbitrary per-call streams, codecs, routing, producer names, or ID sources;
- parallel processing within one partition;
- automatic stream schema migration or retention recovery;
- framework-generated DTO schemas;
- a broker administration plane or consumer-group dashboard.

## 20. Acceptance Criteria

The architecture is implemented when an application can:

1. import one always-global root composed with exactly one adapter module;
2. configure the root synchronously or through an injectable sync/async factory;
3. discover stream handlers across all explicit controllers without scanning;
4. decode typed DTOs and execute the full ToriPy pipeline in exact-owner scopes;
5. stop a partition on decode or validation failure without checkpointing;
6. checkpoint only after successful scope cleanup;
7. preserve serial partition order and bounded cross-partition concurrency;
8. inject the global raw, named configured, and Protocol-token publishers;
9. keep every binding's stream, codec, routing, producer, and ID policy fixed;
10. quiesce and recover without detached work or guessed outcomes;
11. coexist with HTTP, CQRS, SQLAlchemy, and microservices without bridging;
12. pass package, conformance, regression, quality, and artifact gates.
