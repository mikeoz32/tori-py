# API Reference

Tori Py API reference is organized by installed distribution and supported
import facade. Import application-facing symbols from these facades rather than
from implementation modules. A facade's `__all__` is the exact symbol inventory;
this page lists principal symbols and groups instead of duplicating every export.

The API layers are:

1. Root facades for normal application programming.
2. Focused facades where importing a driver, settings, testing, or conformance
   surface should be explicit.
3. Protocols, immutable plans, and compiler helpers for adapter authors.
4. Typed package errors from the same root facade where available.

An exported symbol is public, but public does not mean appropriate at every
layer. Most applications need modules, options, decorators, buses, repositories,
and publishers. Compiler plans, transport protocols, and envelope values are
primarily integration-author contracts.

## `tori-py-framework`

### `tori_py`

The main framework facade is driver-neutral and does not import an HTTP server.
Principal groups are:

- Application: `NestApplication`, `ApplicationAdapter`, `ApplicationBinder`,
  `ApplicationRuntime`, `NoopApplicationAdapter`.
- Modules and graph: `module`, `DeferredModule`, `ModuleSpec`, `ModuleId`,
  `CompiledGraph`, `ProviderRef`, `compile_graph`.
- Providers and scopes: `ValueProvider`, `ClassProvider`, `FactoryProvider`,
  `AliasProvider`, `Inject`, `Scope`, `injectable`, `Token`, `WorkScopeFactory`.
- Controllers and binding: `controller`, `get`, `post`, `put`, `patch`,
  `delete`, `head`, `options`, `route`, `status`, `no_body`, `Body`,
  `BodyStream`, `Path`, `Query`, `Header`, `Cookie`, `Context`.
- WebSockets: `websocket_gateway`, `Socket`, `WebSocketContext`, and
  `current_websocket_context`.
- Pipeline: `middleware`, `guards`, `pipes`, `interceptors`, `filters`, their
  singular and plural `use_*` decorators, `Guard`, `Pipe`, `Interceptor`,
  `ExceptionFilter`, `Middleware`, `ExecutionContext`, and `PipelineResult`.
- Discovery and reflection: `DiscoveryService`, `ModulesContainer`,
  `ProviderView`, `ModuleView`, `Reflector`, `metadata`.
- Portable responses: `HttpResponse`, `ResponseHeaderMetadata`, `header`.
- Options and errors: `ApplicationOptions`, `PipelineOptions`, `ToriPyError`,
  `BootstrapError`, `ResolutionError`, `ScopeError`, `ResourceError`,
  `LifecycleError`, `Diagnostic`, and `DIAGNOSTIC_CODES`.

### Focused framework facades

| Facade | Principal public API |
| --- | --- |
| `tori_py.http` | `HttpContext`, `HttpBodyStream`, `HttpException`, `HttpResponse`, `MsgspecValidationPipe`, `PipelineExecutor`, `RoutePlan`, `ParameterPlan`, `compile_controller_routes`, `compile_routes`, `bind_routes` |
| `tori_py.websocket` | `WebSocketContext`, `WebSocketPlan`, `WebSocketParameterPlan`, `WebSocketPipelineExecutor`, `compile_websocket_gateway`, `compile_websocket_routes`, `bind_websocket_routes` |
| `tori_py.settings` | `SettingsModule`, `SettingsOptions`, `SETTINGS_TOKEN`, `Secret`, `MsgspecCodec`, `MsgspecSettingsDecoder`, `BootstrapContext`, `load_settings`, `secret_paths` |
| `tori_py.starlette` | `StarletteAdapter`, `StarletteOptions`, `ASGIApplication`, `asgi`, `RequestContext`, `WebSocketRequestContext`, `current_request_context` |
| `tori_py.testing` | `TestingModule`, `TestingApplication`, `ProviderOverride`, `http_client` |
| `tori_py.logging` | `LoggingModule`, `PythonLogger`, `LogContext`, `current_log_context`, `use_log_context` |
| `tori_py.starlette.errors` | Driver-specific `problem_response`; prefer `HttpException` or portable `HttpResponse` when native Starlette access is unnecessary |
| `tori_py.cli` | Console entry point only; use the `tori-py run module:factory` command rather than parser or loader internals |

`tori_py.core` re-exports the framework-neutral core inventory, but normal
applications should prefer `tori_py`. HTTP, settings, Starlette, logging, and
testing remain explicit focused imports.

## `tori-py-cqrs-core`

### `tori_py_cqrs_core`

Principal public API:

- Messages and identity: `Message`, `Command`, `Query`, `Event`,
  `message_type_for`.
- Registration: `CommandHandler`, `QueryHandler`, `EventsHandler`, `handles`,
  `HandlerRegistry`, `HandlerRegistration`, `RegisteredHandler`.
- Buses and assembly: `CommandBus`, `QueryBus`, `EventBus`, `CqrsBuilder`,
  `CqrsBuses`, `BusHandles`.
- Transport and providers: `Transport`, `TransportConsumer`,
  `InMemoryTransport`, `TransportState`, `HandlerProvider`,
  `DefaultHandlerProvider`.
- Envelopes: `Envelope`, `ReplyEnvelope`, `DeliveryMetadata`,
  `DeliveryReceipt`, `DispatchContext`.
- Errors: `CqrsError`, validation and duplicate-handler errors,
  `MissingHandlerError`, `NestedCommandDispatchError`, capacity, timeout, and
  transport lifecycle errors.

The root facade is framework-neutral. Do not import a web adapter from core.

## `tori-py-cqrs-fastapi`

### `tori_py_cqrs_fastapi`

The complete facade is intentionally small: `FastAPIAdapter`,
`FastAPIHandlerProvider`, `FastAPIConfigurationError`, and the FastAPI
dependencies `get_command_bus`, `get_query_bus`, and `get_event_bus`.

Use this package with FastAPI. It is not a Tori Py framework adapter.

## `tori-py-cqrs`

### `tori_py_cqrs`

Principal public API:

- Composition: `CqrsModule`, `CqrsModuleOptions`, `TransportFactory`.
- Handlers: `command_handler`, `query_handler`, `event_handler`.
- Explicit escape-hatch bindings: `bind_command_handler`,
  `bind_query_handler`, `bind_event_handler`, `CqrsHandlerBinding`.
- Invocation extension: `CqrsInvocationContext`,
  `CqrsInvocationInterceptor`, `CqrsInterceptorBinding`,
  `CqrsInterceptorPhase`, `CqrsInvocationCompletion`, `CqrsScopeCompletion`,
  `use_cqrs_interceptors`.
- Errors: `ToriPyCqrsError`, configuration, lifecycle, pipeline, handler-exit,
  and cancellation variants.

Messages and buses remain owned by `tori_py_cqrs_core`; import them there.

## `tori-py-cqrs-event-sourcing-core`

### `tori_py_cqrs_event_sourcing_core`

Principal public API:

- Domain: `AggregateRoot`, `PendingEvent`, `RecordedEvent`, `StreamId`.
- Schemas and codecs: `EventSchema`, `EventSchemaRegistry`, `EventEncoder`,
  `EventDecoder`, `EventUpcaster`, `EventSourcingLimits`.
- Store contracts: `EventStore`, `EventStoreTransaction`, `AppendEvent`,
  `StoredEvent`, `CommitResult`, `InMemoryEventStore`.
- Repository and transaction: `EventSourcedRepository`,
  `EventSourcingUnitOfWork`.
- Outcomes: `ConfirmedCommit`, `ConfirmedNonCommit`, `IndeterminateCommit`,
  `UnitOfWorkOutcome`.
- Errors: `EventSourcingError` and typed aggregate, schema, codec, store,
  concurrency, duplicate-ID, Unit-of-Work, and indeterminate-commit errors.

The in-memory store is part of the public semantic reference, not a durable
adapter.

## `tori-py-cqrs-event-sourcing`

### `tori_py_cqrs_event_sourcing`

Principal public API:

- Composition: `CqrsEventSourcingModule`, `CqrsEventSourcingOptions`,
  `UnitOfWorkFactory`, `default_unit_of_work_factory`.
- Repository and transaction declarations: `aggregate_repository`,
  `use_event_sourcing`, `event_sourcing_transaction`.
- Synchronization: `CommandSynchronization`.
- Keyed tokens: `get_event_store_token`, `get_schema_registry_token`,
  `get_command_synchronization_token`, `get_transaction_interceptor_token`.
- Errors and outcome preservation: `CqrsEventSourcingError`,
  `CommandTransactionUnavailableError`, `CommandSynchronizationStateError`,
  `ConfirmedCommandFinalizationError`,
  `ConfirmedNonCommitFinalizationError`,
  `IndeterminateCommandFinalizationError`, `CommandCancellationError`, and
  `CommandFinalizationPhase`.

Aggregate and EventStore contracts remain in the core event-sourcing facade.

## `tori-py-sqlalchemy`

### `tori_py_sqlalchemy`

Principal public API:

- Composition: `SqlAlchemyModule`, `SqlAlchemyOptions`,
  `SqlAlchemySessionOptions`, `SqlAlchemyOptionsFactory`.
- Operations: `EntityManager`, `ExecuteParams`.
- Repositories: `Repository`, `repository`, `inject_repository`.
- Keyed tokens: `get_engine_token`, `get_session_factory_token`,
  `get_entity_manager_token`, `get_repository_token`.
- Errors: `SqlAlchemyIntegrationError`, `SqlAlchemyConfigurationError`,
  `TransactionContextError`.

SQLAlchemy's own mapped classes, statements, loader options, engine types, and
exceptions remain SQLAlchemy APIs.

## `tori-py-openapi`

### `tori_py_openapi`

Principal public API:

- Composition and options: `OpenApiModule`, `OpenApiOptions`, `OpenApiInfo`,
  `OpenApiServer`, `BearerSecurityScheme`, `SwaggerUiOptions`.
- Metadata: `api_tags`, `api_operation`, `api_parameter`, `api_response`,
  `api_security`, `api_public`, `api_exclude`.
- Errors: `OpenApiError`, `OpenApiConfigurationError`,
  `OpenApiMetadataError`, `OpenApiSchemaError`.

Only HTTP bearer security schemes are modeled in this release. Use
`api_security(name)` with its default `scopes=()`; non-empty scope arrays are
reserved for a future OAuth2 or OpenID Connect API.

The package intentionally exposes metadata and module composition, not a second
HTTP router or runtime response validator.

## `tori-py-microservices`

### `tori_py_microservices`

This large facade serves applications and transport authors. Principal groups
are:

- Server composition: `MicroservicesModule`, `MicroservicesOptions`,
  `MicroservicesRoot`, `ServiceIdentity`, `ServiceRuntime`.
- Handlers and contexts: `rpc`, `event_handler`, `Payload`, `Context`, `Header`,
  `Headers`, `Inject`, `RpcContext`, `EventContext`, `EventDispatchMode`.
- Clients and contracts: `ClientsModule`, `ServiceCluster`, `ServiceProxy`,
  `ServiceClusterOptions`, `service_contract`, `rpc_call`,
  `ProtocolServiceProxy`.
- Event publication: `EventDispatcher`, `PublicationReceipt`.
- Portable transport: `ClientTransport`, `ServerTransport`, their factories,
  `TransportStatus`, `EncodedDelivery`, `Publication`, `EventSubscription`.
- In-memory reference: `InMemoryBroker`, `InMemoryClientTransport`,
  `InMemoryServerTransport`.
- Wire and limits: `MessageCodec`, `MsgspecJsonMessageCodec`, `MessageLimits`,
  request/response/event envelopes and stable identity values.
- Errors: `MicroservicesError`, invocation and authorization errors, transport
  outcome errors, RPC client errors, wire errors, and RabbitMQ errors.

### `tori_py_microservices.rabbitmq`

The explicit RabbitMQ facade provides `RabbitMqModule`, `RabbitMqOptions`,
`RabbitMqTransport`, client/server transport factories, connection/status
types, publisher, topology declaration values and compilers, keyed token
helpers, and `require_aio_pika`.

RabbitMQ is installed with `tori-py-microservices[rabbitmq]`. Importing the base
facade or RabbitMQ facade does not open a connection.

### `tori_py_microservices.testing`

`assert_transport_conformance` is the public conformance helper for transport
implementations. It complements, rather than replaces, real-broker failure
tests.

## `tori-py-persistent-streams-core`

### `tori_py_persistent_streams_core`

Principal public API:

- Records and streams: `AppendRequest`, `StoredRecord`, `StreamDefinition`,
  `StreamLimits`, `PublishReceipt`, `PublishOutcome`, `RecordPage`.
- Start and progress: `Beginning`, `End`, `ExactOffset`, `Timestamp`,
  `RelativeTime`, `ResumeCursor`, `AvailableBounds`, `StartModeCapabilities`.
- Consumption: `Subscription`, `ConsumerRunner`, `PartitionLease`,
  `CheckpointStrategy`, `ExternalCheckpointStrategy`, `CheckpointStore`.
- Log contracts: `PersistentLog`, `PersistentStreamAdapter`,
  `InMemoryPersistentLog`, `InMemoryCheckpointStore`.
- Routing: `PartitionRouter`, `Sha256PartitionRouter`,
  `DEFAULT_PARTITION_ROUTER`.
- Errors: `PersistentStreamsError` and typed validation, retention, ownership,
  checkpoint, poison-record, lifecycle, and adapter-contract errors.

### `tori_py_persistent_streams_core.testing`

`run_conformance_suite`, the individual `conformance_*` cases,
`AdapterFactory`, and `TrimCapablePersistentLog` are public adapter-author test
contracts. Conformance proves portable semantics, not broker durability,
clustering, or outage behavior.

## `tori-py-persistent-streams`

### `tori_py_persistent_streams`

Principal public API:

- Composition: `PersistentStreamsModule`, `PersistentStreamsOptions`,
  `PersistentStreamsRuntimeOptions`, `StreamBinding`, `PublisherRegistration`.
- Handler mapping: `stream_handler`, `StreamPayload`, `StreamRecordContext`,
  `StreamHeaders`, `StreamHeader`, `StreamPartition`, `StreamOffset`,
  `StreamInject`, `StreamContext`.
- Publishing: `StreamPublisher`, `ConfiguredStreamPublisher`, `stream_publish`,
  `stream_publisher_token`, `PublishReceipt`, `PublishOutcome`.
- Adapter and runtime: `StreamAdapterFactory`, `StreamCodec`,
  `PartitionKeyResolver`, `PublishingIdSource`, `StreamRuntime`,
  `PartitionStatus`.
- Extension plans and compilers: stream handler/parameter/pipeline plans,
  registries, pipeline executor, and controller/discovery compilers.
- Errors: `ToriPyPersistentStreamsError`, configuration, compilation,
  invocation, runtime, and publication-saturation errors.

### `tori_py_persistent_streams.testing`

`InMemoryPersistentStreamsModule` and `InMemoryStreamAdapterFactory` provide
normal Tori Py composition for tests and examples. They are not durable storage.

## `tori-py-persistent-streams-rabbitmq`

### `tori_py_persistent_streams_rabbitmq`

The lazy root facade provides:

- Composition and options: `RabbitMqPersistentStreamsModule`,
  `RabbitMqPersistentStreamsOptions`, `RabbitMqConnectionOptions`,
  `RabbitMqTlsOptions`, `DeclarationMode`, `SaslMechanism`.
- Adapter: `RabbitMqStreamAdapterFactory`, `RabbitMqPersistentLog`,
  `RabbitMqPartitionLease`, `TopologyPreflight`,
  `RABBITMQ_START_MODE_CAPABILITIES`.
- Envelope interoperability: `RecordEnvelope`, `EnvelopeLimits`, `CONTENT_TYPE`,
  and the encode/decode helpers.
- Facade errors: `RabbitMqPersistentStreamsError`, `TopologyConflictError`,
  `EnvelopeError`.

The lazy facade performs no broker I/O on import. Its public surface does not
remove the adapter's provisional deployment restrictions.

## `tori-py-liveview`

### `tori_py_liveview`

Principal public API:

- Composition: `LiveViewModule`, `LiveViewOptions`.
- Page and component lifecycle: `LiveView`, `LiveComponent`, `MountContext`,
  `live_view`.
- Rendering: `Rendered`, `SafeHtml`, `rendered`, `raw`.
- Errors: `LiveViewError`, `LiveViewConfigurationError`, `UnknownEventError`.

The package implements Opal protocol-v2 page snapshots, structural diffs,
stateful components, targeted events, stale resynchronization, heartbeats, title
updates, and reconnect joins. Nested components, streams, uploads, and
`send_info` are not part of the current server surface.

## Reading generated reference

When a generated symbol page is available, read it together with the owning
guide:

- Signatures and attributes answer what can be called.
- Package and recipe guides answer when it is appropriate.
- Architecture and package operations guides define hard lifecycle and broker
  guarantees.
- [Errors and Diagnostics](errors-and-diagnostics.md) explains failure handling.
- [Examples](examples.md) identifies tested, runnable compositions.

Do not construct behavior from an implementation module merely because Python
allows importing it. If a required contract is absent from the supported
facades, treat it as unavailable and request a public API rather than depending
on a private path.
