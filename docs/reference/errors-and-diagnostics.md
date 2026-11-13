# Errors and Diagnostics

Tori Py packages use typed exceptions to preserve ownership and outcome facts.
Catch the narrowest type that corresponds to a decision your application can
make. A loggable diagnostic, an HTTP response, a retry decision, and a process
control signal are different concerns and must not be collapsed into one generic
error handler.

## Rules for callers

1. Catch configuration errors at composition or startup and fail readiness.
2. Convert only expected application failures into public HTTP or RPC errors.
3. Treat timeout as a caller observation, not proof that remote or durable work
   did not happen.
4. Preserve typed confirmed, rejected, and indeterminate outcomes.
5. Never swallow `asyncio.CancelledError`, `KeyboardInterrupt`, or `SystemExit`.
6. Log bounded, allowlisted fields. Do not log payloads, secrets, credentials,
   raw headers, arbitrary exception representations, or complete DTOs.

## Framework diagnostics

Every `ToriPyError` has:

- `diagnostic_code`: a stable machine-readable string;
- `diagnostic`: a `Diagnostic` containing `code`, a human-readable `message`,
  and immutable `details`;
- its normal exception message for local debugging.

Each class has a default code. Most raise sites pass a more specific code from
the [catalog below](#framework-diagnostic-codes), so handle `diagnostic_code`
rather than the class alone when the distinction matters.

Prefer code-based handling over matching message text:

<!-- docs-test: skip -->

```python
from tori_py import BootstrapError

try:
    application = await create_application()
except BootstrapError as error:
    logger.error(
        "Application compilation failed",
        diagnostic_code=error.diagnostic_code,
    )
    raise
```

Do not automatically emit `error.diagnostic.details`. Details are structured for
diagnosis, but the safety of application tokens, paths, or values still depends
on the originating boundary and the destination log.

`ScopeFinalizationError` retains `body_error` and ordered `cleanup_errors` after
all cleanup was attempted. `ScopeCancellationError` is an
`asyncio.CancelledError` subtype that retains cancellation plus cleanup errors.
Code must preserve those distinctions; cleanup failure must not turn cancellation
into an ordinary retryable exception.

### Framework exception types

All types are exported from `tori_py` unless another module is named.

| Exception | Base | Default code | Raised when |
| --- | --- | --- | --- |
| `ToriPyError` | `Exception` | `tori_py.error` | Base class; carries `diagnostic` and `diagnostic_code` |
| `BootstrapError` | `ToriPyError` | `bootstrap.error` | Modules, providers, controllers, routes, gateways, options, or test overrides cannot be compiled |
| `ResolutionError` | `ToriPyError` | `provider.resolution_error` | A provider cannot be resolved at runtime |
| `ScopeError` | `ToriPyError` | `provider.scope_error` | A scope is declared or used incorrectly, such as resolving a request-scoped provider without a scope |
| `ScopeClosedError` | `ScopeError` | `scope.closed` | A request or work scope, or the container, is used after it closed |
| `ResourceError` | `ToriPyError` | `resource.error` | Resource acquisition or cleanup fails |
| `ScopeFinalizationError` | `ResourceError` | `resource.cleanup_error` | A scope ended with a body error, cleanup errors, or both; fields `body_error`, `cleanup_errors` |
| `ScopeCancellationError` | `asyncio.CancelledError` | — | A scope was cancelled and cleanup also failed; fields `cancellation`, `body_error`, `cleanup_errors` |
| `LifecycleError` | `ToriPyError` | `lifecycle.error` | A lifecycle hook has an invalid signature or fails |
| `SettingsError` | `ToriPyError` | `settings.error` | Settings sources cannot be read or decoded |
| `PipelineStateError` | `ToriPyError` | `pipeline.invalid_state` | A pipeline, interceptor, or `next` callback is used out of order, such as calling `next` twice |
| `ApplicationStateError` | `ToriPyError` | `application.invalid_state` | An application or adapter operation is invalid in the current state, such as starting twice or using an unattached adapter |
| `tori_py.websocket.WebSocketForbidden` | `ToriPyError` | `websocket.forbidden` | A guard denied an unaccepted WebSocket connection |
| `tori_py.http.HttpException` | `Exception` | — | An expected HTTP failure that the adapter renders as Problem Details |

### Framework diagnostic codes

`tori_py.DIAGNOSTIC_CODES` is the inventory of stable framework codes. The
"Inventory" column shows whether a code is in it today. Codes marked "log" are
the `code` field of a framework log record rather than an exception.

#### Modules

| Code | Raised as | When | Inventory |
| --- | --- | --- | --- |
| `module.invalid_declaration` | `BootstrapError` | An import is not a module class or deferred descriptor, a deferred module is not a class, or a dynamic key is empty or `"static"` | no |
| `module.duplicate_metadata` | `BootstrapError` | `@module` is applied twice to one class | no |
| `module.invalid_constructor` | `BootstrapError` | A module class has required constructor arguments or cannot be inspected | yes |
| `module.cycle` | `BootstrapError` | Module imports form a cycle | yes |
| `module.dynamic_conflict` | `BootstrapError` | Different deferred descriptors use the same `(module class, key)` identity | yes |
| `module.static_dynamic_conflict` | `BootstrapError` | One module class is used both as a static and as a dynamic module | yes |
| `module.materialization_error` | `BootstrapError` | A deferred module factory raised; a `SettingsError` propagates unchanged instead | yes |
| `module.invalid_export` | `BootstrapError` | A module exports a token it neither provides nor imports | yes |

#### Providers and scopes

| Code | Raised as | When | Inventory |
| --- | --- | --- | --- |
| `provider.invalid_token` | `BootstrapError` | A token is not a class or a non-empty string | no |
| `provider.invalid_scope` | `BootstrapError` | A provider uses an unsupported scope value | no |
| `provider.invalid_declaration` | `BootstrapError` | A declaration is unsupported or malformed: a non-singleton value provider, a class provider without a class, a non-callable factory, an undecorated class in `providers=`, or method interceptors on a provider that cannot be proxied | yes |
| `provider.invalid_signature` | `BootstrapError` | Constructor or factory annotations cannot be compiled: unannotated required or variadic parameters, or several `Inject` markers | yes |
| `provider.duplicate` | `BootstrapError` | One module declares the same token twice | yes |
| `provider.reserved_token` | `BootstrapError` | A declaration uses a token reserved for a framework dependency | yes |
| `provider.unresolved` | `BootstrapError` | A dependency, alias target, pipeline provider, route dependency, or method interceptor provider is not visible from the module that needs it | yes |
| `provider.ambiguous` | `BootstrapError` | Several direct imports or global modules export the same token | yes |
| `provider.cycle` | `BootstrapError` | Provider dependencies form a cycle | yes |
| `provider.alias_cycle` | `BootstrapError` | A dependency cycle passes through an alias provider | yes |
| `provider.scope_violation` | `BootstrapError` | A singleton provider depends, directly or indirectly, on a request-scoped provider | yes |
| `provider.resolution_error` | `ResolutionError` | Default code of `ResolutionError` | no |
| `provider.scope_error` | `ScopeError` | Default code of `ScopeError` | no |
| `scope.closed` | `ScopeClosedError` | Default code of `ScopeClosedError` | no |

#### Reflection and discovery

| Code | Raised as | When | Inventory |
| --- | --- | --- | --- |
| `reflection.invalid_metadata` | `BootstrapError` | A metadata key name is empty, the target is not a class or function, the stored metadata is invalid, or a lookup uses another key type | yes |
| `reflection.duplicate_metadata` | `BootstrapError` | One metadata key is attached twice to the same target | yes |
| `discovery.invalid_filter` | `BootstrapError` | A discovery filter is not iterable or contains invalid values | yes |

#### Controllers, routes, and gateways

| Code | Raised as | When | Inventory |
| --- | --- | --- | --- |
| `controller.invalid_declaration` | `BootstrapError` | A controller is not a singleton provider, has invalid metadata such as a non-string prefix, or a module lists a non-class controller | yes |
| `controller.invalid_signature` | `BootstrapError` | A compiled handler is not callable or controller annotations cannot be inspected | yes |
| `controller.duplicate_metadata` | `BootstrapError` | `@controller` is applied twice to one class | no |
| `route.invalid_signature` | `BootstrapError` | A route method, status, native ASGI path, pipeline registration, or response header declaration is invalid | yes |
| `route.invalid_binding` | `BootstrapError` | A route parameter has no or several binding markers, is variadic, adds a second body, uses an incompatible context type, or has an invalid source name or body-stream limit | yes |
| `route.duplicate` | `BootstrapError` | Two routes use the same method and path | yes |
| `route.duplicate_metadata` | `BootstrapError` | A route decorator, `@status`, or `@no_body` is applied twice to one handler | no |
| `route.duplicate_pipeline_decorator` | `BootstrapError` | The same pipeline decorator, such as `@guards`, is applied twice to one target | yes |
| `gateway.invalid_declaration` | `BootstrapError` | A gateway path is not a string, a gateway is not a singleton provider, or gateway metadata is missing | yes |
| `gateway.invalid_signature` | `BootstrapError` | A gateway has no callable handler or its annotations cannot be inspected | yes |
| `gateway.invalid_binding` | `BootstrapError` | A gateway does not have exactly one `Socket()` binding, a parameter has no or several markers or is variadic, or a context type is incompatible | yes |
| `gateway.duplicate` | `BootstrapError` | Two gateways use the same path | yes |
| `gateway.duplicate_metadata` | `BootstrapError` | `@websocket_gateway` is applied twice to one class | yes |

#### Settings

| Code | Raised as | When | Inventory |
| --- | --- | --- | --- |
| `settings.source_error` | `SettingsError` | A settings file, dotenv file, or YAML source cannot be read or parsed, the model is not a class, or an override targets a secret path; also `BootstrapError` for an empty bootstrap override path | yes |
| `settings.decode_error` | `SettingsError` | A value fails type conversion or the model cannot be decoded | yes |
| `settings.error` | `SettingsError` | Default code of `SettingsError` | no |

#### Resources and lifecycle

| Code | Raised as | When | Inventory |
| --- | --- | --- | --- |
| `resource.acquire_error` | `ResourceError` | A resource is entered after its resource stack closed | yes |
| `resource.cleanup_error` | `ScopeFinalizationError`; log | Resource cleanup failed, or a managed resource's exit returned a truthy value, which would suppress an exception | yes |
| `resource.lingering_resource` | log | Resource cleanup exceeded the shutdown deadline, or request-scope resources stayed open after the shutdown grace | yes |
| `resource.lingering_worker` | log | A synchronous resource worker failed or kept running past the shutdown deadline | yes |
| `resource.error` | `ResourceError` | Default code of `ResourceError` | no |
| `lifecycle.startup_error` | `LifecycleError` | A lifecycle hook is not async, has an invalid signature, or cannot be inspected | yes |
| `lifecycle.lingering_task` | log | A shutdown operation or request task exceeded the shutdown deadline or grace | yes |
| `lifecycle.shutdown_timeout` | — | In the inventory but not emitted by the current runtime | yes |
| `lifecycle.error` | `LifecycleError` | Default code of `LifecycleError` | no |

#### Application, pipeline, and testing

| Code | Raised as | When | Inventory |
| --- | --- | --- | --- |
| `application.invalid_options` | `BootstrapError` | Application or adapter options are invalid, or an adapter or binder does not implement the adapter protocol | no |
| `application.invalid_state` | `ApplicationStateError`, `BootstrapError` | An operation is invalid in the current application state, such as reading an adapter's ASGI app before startup | yes |
| `pipeline.invalid_state` | `PipelineStateError` | Default code of `PipelineStateError` | no |
| `testing.builder_sealed` | `BootstrapError` | A `TestingModule` builder is changed after `compile()` | yes |
| `testing.invalid_module` | `BootstrapError` | A testing call names a module that is not in the compiled graph | yes |
| `testing.invalid_override` | `BootstrapError` | An override target is not present in the compiled graph | yes |
| `testing.private_provider` | `BootstrapError` | An override targets a provider its module does not export | yes |
| `testing.httpx_unavailable` | `BootstrapError` | An HTTP test client is requested without the `testing` extra | yes |
| `websocket.forbidden` | `WebSocketForbidden` | A guard denied an unaccepted WebSocket connection | no |

## HTTP errors

`tori_py.http.HttpException` represents an expected HTTP failure. Its `detail`,
`title`, optional `errors`, and safe response headers are intentionally public
and are rendered as RFC 9457 Problem Details by the selected HTTP adapter.
Validation errors use the `errors` extension. A guard returning `False` maps to
a standard 403 response.

Unexpected exceptions produce a sanitized 500 response without a source
traceback or arbitrary exception text. Tori Py's emergency HTTP diagnostic uses
a fresh event ID and fixed event code; it deliberately excludes request data,
caller correlation IDs, exception text, representations, and tracebacks.

Filters catch ordinary `Exception` values only. Re-raise errors a filter does not
own. Once response transmission has started, a later failure cannot safely be
re-rendered as another Problem Details response.

The framework-owned `X-Request-ID` is correlation metadata, not authentication.
It can be returned to a caller and used to locate normal application logs, but
must not be trusted as identity or copied into emergency diagnostics.

## Settings, SQLAlchemy, OpenAPI, and LiveView

These integration errors inherit `ToriPyError`, so they expose the same
diagnostic contract.

| Exception | Base | Code | Raised when |
| --- | --- | --- | --- |
| `tori_py_sqlalchemy.SqlAlchemyIntegrationError` | `ToriPyError` | `sqlalchemy.integration_error` | Base class for the integration |
| `tori_py_sqlalchemy.SqlAlchemyConfigurationError` | `SqlAlchemyIntegrationError` | `sqlalchemy.configuration_error` | Module options, engine options, the options factory result, the engine provider, or the module key are invalid |
| `tori_py_sqlalchemy.TransactionContextError` | `SqlAlchemyIntegrationError` | `sqlalchemy.transaction_context_error` | An operation needs a transaction it does not have, such as `with_for_update` without an explicit transaction, or a transaction context is used from a child task or after it ended |
| `tori_py_openapi.OpenApiError` | `ToriPyError` | `openapi.error` | Base class for the integration |
| `tori_py_openapi.OpenApiConfigurationError` | `OpenApiError` | `openapi.configuration_error` | `OpenApiOptions` or Swagger UI options are invalid |
| `tori_py_openapi.OpenApiMetadataError` | `OpenApiError` | `openapi.metadata_error` | A documentation decorator has invalid arguments, is applied twice, or conflicts with another, such as `api_public` with `api_security` |
| `tori_py_openapi.OpenApiSchemaError` | `OpenApiError` | `openapi.schema_error` | An annotation, path, component, operation ID, or security reference cannot produce a valid document, including annotations nested beyond the limits |
| `tori_py_liveview.LiveViewError` | `ToriPyError` | `liveview.error` | Base class; also invalid navigation and component use at runtime |
| `tori_py_liveview.LiveViewConfigurationError` | `LiveViewError` | `liveview.configuration_error` | `LiveViewOptions`, `@live_view`, `LiveSession`, or `LiveViewModule.for_root()` arguments are invalid |
| `tori_py_liveview.UnknownEventError` | `LiveViewError` | `liveview.unknown_event` | A page or component does not handle an event; the event is acknowledged without a render |
| `tori_py_liveview.UnknownInfoError` | `LiveViewError` | `liveview.unknown_info` | A page does not handle a `send_info()` message; the socket closes with `1011` |
| `tori_py_liveview.UnknownAsyncError` | `LiveViewError` | `liveview.unknown_async` | A page or component does not handle the result of its `start_async()` work; the socket closes with `1011` |

The SQLAlchemy, OpenAPI, and LiveView configuration errors generally fail
compilation or startup. Do not convert them into a
successful readiness result. SQLAlchemy driver exceptions remain SQLAlchemy or
driver errors unless the integration specifically owns the failed contract.
Database URLs and engine options are designed to avoid secret-bearing
representations, but application logs must still avoid emitting raw connection
configuration.

`SettingsError` and its diagnostic codes identify source and decode failures.
`Secret[T]` marks settings paths for redaction; CLI overrides targeting secret
paths are rejected. Redaction is not permission to log the rest of a settings
object wholesale.

## CQRS

`tori_py_cqrs_core.CqrsError` is the framework-neutral base. CQRS exceptions do
not carry the framework `Diagnostic` object; handle their types and documented
fields.

| Exception (`tori_py_cqrs_core`) | Base | Fields | Raised when |
| --- | --- | --- | --- |
| `CqrsError` | `Exception` | — | Base class |
| `CqrsValidationError` | `CqrsError` | — | A core contract receives invalid data |
| `InvalidHandlerRegistrationError` | `CqrsValidationError` | — | A handler registration does not satisfy its contract |
| `DuplicateHandlerError` | `CqrsValidationError` | `message_type` | Base class for duplicate registrations |
| `DuplicateCommandHandlerError` | `DuplicateHandlerError` | `message_type` | A command type has more than one handler |
| `DuplicateQueryHandlerError` | `DuplicateHandlerError` | `message_type` | A query type has more than one handler |
| `EnvelopeValidationError` | `CqrsValidationError` | — | A bus receives the wrong message kind, such as an event passed to `CommandBus.execute`, or an envelope's delivery metadata is invalid |
| `MissingHandlerError` | `CqrsError` | `message_type` | A command or query has no handler |
| `NestedCommandDispatchError` | `CqrsError` | — | A command handler executes another command through its own active command bus |
| `QueueCapacityError` | `CqrsError` | `timeout` | A bounded transport queue cannot accept work in time |
| `RequestTimeoutError` | `CqrsError` | `message_id`, `correlation_id`, `timeout` | The caller stopped waiting for a reply |
| `InvalidReplyCorrelationError` | `CqrsError` | `expected`, `actual` | A reply does not match its request's correlation ID |
| `InvalidTransportReplyError` | `CqrsError` | — | A request consumer returned no valid reply |
| `TransportLifecycleError` | `CqrsError` | — | Base class for transport lifecycle failures |
| `TransportNotStartedError` | `TransportLifecycleError` | — | Work is submitted before the transport starts |
| `TransportStoppedError` | `TransportLifecycleError` | — | Work is submitted after the transport stopped |
| `InvalidLifecycleTransitionError` | `TransportLifecycleError` | `operation`, `state` | A lifecycle operation is invalid in the transport's state |

| Exception | Base | Fields | Raised when |
| --- | --- | --- | --- |
| `tori_py_cqrs.ToriPyCqrsError` | `CqrsError` | — | Base class for the ToriPy integration |
| `tori_py_cqrs.CqrsConfigurationError` | `ToriPyCqrsError` | — | A handler or interceptor declaration is invalid, such as a synchronous `handle` or `intercept` method |
| `tori_py_cqrs.CqrsLifecycleError` | `ToriPyCqrsError` | — | Coordinated bus startup or shutdown fails |
| `tori_py_cqrs.CqrsPipelineStateError` | `ToriPyCqrsError` | — | The invocation pipeline is used out of order, such as calling `next` twice, or a completion mapper breaks its contract |
| `tori_py_cqrs.CqrsHandlerExitError` | `ToriPyCqrsError` | `body_error`, `callback_errors` | A handler failed, a terminal callback failed, or both |
| `tori_py_cqrs.CqrsHandlerExitCancellationError` | `asyncio.CancelledError` | `cancellation`, `secondary_errors` | A handler or terminal callback was cancelled and other failures must be kept |
| `tori_py_cqrs_fastapi.FastAPIConfigurationError` | `RuntimeError` | — | A FastAPI app is used before CQRS buses were initialized on it |

For an accepted in-memory command or query, caller timeout or cancellation stops
waiting but does not necessarily cancel worker-owned handling. Never infer
rollback from `RequestTimeoutError` alone.

## Event sourcing

Event-sourcing core has typed families for aggregate lifecycle, schema and codec,
EventStore, repository, Unit of Work, optimistic concurrency, duplicate event
IDs, and resource limits. All types below are exported from
`tori_py_cqrs_event_sourcing_core` except `RepositoryError`, which is a base
class in the hierarchy but is not exported from the facade.

| Exception | Base | Fields | Raised when |
| --- | --- | --- | --- |
| `EventSourcingError` | `Exception` | — | Base class |
| `EventSourcingValidationError` | `EventSourcingError` | — | A value violates its contract |
| `InvalidStreamIdError` | `EventSourcingValidationError` | — | A stream category or key is empty, untrimmed, or not printable |
| `InvalidEventMetadataError` | `EventSourcingValidationError` | — | Occurrence metadata is invalid: non-UUID identities, a naive timestamp, or invalid headers |
| `InvalidEventRecordError` | `EventSourcingValidationError` | — | An event record of any stage is malformed, such as a non-`Event` value or a wrong record type |
| `ResourceLimitError` | `EventSourcingValidationError` | — | A payload, header, upcast, append, or transaction limit from `EventSourcingLimits` is exceeded |
| `AggregateError` | `EventSourcingError` | — | Base class for aggregate failures |
| `AggregateLifecycleError` | `AggregateError` | — | An aggregate operation is invalid in its current state |
| `AggregateFaultedError` | `AggregateLifecycleError` | — | A faulted aggregate is used again; discard and reload it |
| `AggregateEnlistedError` | `AggregateLifecycleError` | — | An enlisted aggregate is changed, replayed, or enlisted a second time |
| `AggregateOwnershipError` | `AggregateLifecycleError` | — | A Unit of Work that does not own an aggregate's enlistment changes it |
| `AggregateCommitStateError` | `AggregateLifecycleError` | — | A staged aggregate no longer matches its commit plan, for example its pending events changed after enlistment |
| `AggregateReplayError` | `AggregateError` | — | History is not one contiguous stream starting after the current version |
| `AggregateStreamMismatchError` | `AggregateReplayError` | `expected`, `actual` | One aggregate is associated with different streams |
| `AggregateTypeMismatchError` | `AggregateError` | `expected`, `actual` | A repository receives an aggregate of another class |
| `SchemaError` | `EventSourcingError` | — | Base class for schema and codec failures |
| `SchemaValidationError` | `SchemaError`, `EventSourcingValidationError` | — | A schema declaration or codec result is invalid |
| `DuplicateEventSchemaError` | `SchemaValidationError` | — | An alias or event class is registered twice |
| `SchemaRegistryFrozenError` | `SchemaValidationError` | — | A frozen registry is changed |
| `SchemaRegistryNotFrozenError` | `SchemaValidationError` | — | An unfrozen registry is used for persistence |
| `UnknownEventSchemaError` | `SchemaError` | — | No schema is registered for an event class or persisted alias |
| `UnsupportedEventSchemaVersionError` | `SchemaError` | — | Stored data uses a schema version newer than the current one |
| `EventCodecError` | `SchemaError` | — | An encoder or decoder fails or returns a value that breaks the schema contract |
| `EventUpcastError` | `SchemaError` | — | An event cannot be upcast to the current schema version |
| `EventStoreError` | `EventSourcingError` | — | Base class for EventStore failures |
| `EventStoreTransactionError` | `EventStoreError` | — | Transaction rules are violated, such as an empty append batch or use in the wrong state |
| `DuplicateStreamAppendError` | `EventStoreTransactionError` | `stream_id` | One transaction stages the same stream twice |
| `OptimisticConcurrencyError` | `EventStoreError` | `stream_id`, `expected_version`, `actual_version` | A stream's committed version differs from the expected version |
| `DuplicateEventIdError` | `EventStoreError` | `event_id` | An event ID is already committed or staged |
| `ConfirmedCommitError` | `EventStoreError` | — | Raised by an EventStore adapter to confirm that a commit attempt did not change storage; the Unit of Work records `ConfirmedNonCommit` |
| `IndeterminateCommitError` | `EventStoreError` | — | An adapter cannot prove whether a commit succeeded |
| `ConfirmedCommitCleanupError` | `EventSourcingError` | `result`, `cleanup_error` | Storage committed, but transaction-context cleanup failed afterwards |
| `RepositoryError` (not exported) | `EventSourcingError` | — | Base class for repository and Unit of Work failures |
| `AggregateNotFoundError` | `RepositoryError` | — | `repository.get()` finds no stream for a required aggregate |
| `UnitOfWorkError` | `RepositoryError` | — | Base class for Unit of Work failures |
| `UnitOfWorkLifecycleError` | `UnitOfWorkError` | — | A Unit of Work is entered, exited, or used in the wrong state |
| `DuplicateAggregateSaveError` | `UnitOfWorkError` | — | One aggregate is saved twice in one Unit of Work |
| `DuplicateStreamAggregateError` | `UnitOfWorkError` | — | Two aggregate instances target one enlisted stream |
| `CommitResultMismatchError` | `UnitOfWorkError` | — | An EventStore returns a commit result that does not match the staged events |

The ToriPy integration (`tori_py_cqrs_event_sourcing`) adds:

| Exception | Base | Fields | Raised when |
| --- | --- | --- | --- |
| `CqrsEventSourcingError` | `Exception` | — | Base class |
| `CqrsEventSourcingConfigurationError` | `CqrsEventSourcingError` | — | Module keys, aggregate registrations, schema registries, or interceptor use are invalid, such as an unfrozen registry or an event-sourcing interceptor on a query handler |
| `CommandTransactionUnavailableError` | `CqrsEventSourcingError` | — | A repository is resolved or used outside its owning decorated command body |
| `CommandSynchronizationStateError` | `CqrsEventSourcingError` | — | A commit synchronization is registered outside the owning command body or when the outcome is unavailable |
| `ConfirmedCommandFinalizationError` | `CqrsEventSourcingError` | `commit_result`, `handler_result`, `phase`, `primary_error`, `secondary_errors` | The commit is confirmed, but synchronization or cleanup failed afterwards |
| `ConfirmedNonCommitFinalizationError` | `CqrsEventSourcingError` | `outcome`, `phase`, `primary_error`, `secondary_errors` | No commit happened, and finalization also failed |
| `IndeterminateCommandFinalizationError` | `CqrsEventSourcingError` | `outcome`, `phase`, `primary_error`, `secondary_errors` | The commit outcome is unknown, and finalization also failed |
| `CommandCancellationError` | `asyncio.CancelledError` | `outcome`, `cancellation`, `phase`, `secondary_errors` | The command was cancelled; the exact persistence outcome is kept |

`phase` is a `CommandFinalizationPhase`: `handler_rollback`,
`handler_finalization`, `commit`, `synchronization`, `scope_cleanup`, or
`uow_cleanup`.

The retry-critical distinction is:

| Outcome | Meaning | Safe default |
| --- | --- | --- |
| `ConfirmedCommit` | The store returned a validated commit result | Do not repeat the command as though it rolled back. Reconcile any later callback or cleanup failure. |
| `ConfirmedNonCommit` | The transaction confirmed no commit | Application policy may compensate or retry if the command itself is idempotent. |
| `IndeterminateCommit` / `IndeterminateCommitError` | The adapter cannot prove whether commit happened | Do not blindly retry. Reconcile using stable command/event identity. |

The Tori Py integration preserves these facts in
`ConfirmedCommandFinalizationError`, `ConfirmedNonCommitFinalizationError`,
`IndeterminateCommandFinalizationError`, and `CommandCancellationError`.
Inspect `phase`, the typed outcome or commit result, `primary_error`, and bounded
secondary-error metadata. A confirmed commit followed by cleanup failure is not
a rollback.

Optimistic concurrency and duplicate event IDs retain their core types when no
secondary finalization failure requires an outcome-preserving wrapper.

## Microservices

`MicroservicesError` subclasses have a stable class-level `diagnostic_code`. All
types are exported from `tori_py_microservices`. Codes start with
`microservices.`, which the table omits.

| Exception | Base | Code | Raised when |
| --- | --- | --- | --- |
| `MicroservicesError` | `Exception` | `error` | Base class |
| `OptionalDependencyError` | `MicroservicesError` | `optional_dependency` | An optional transport is used without its extra; fields `dependency`, `extra` |
| `IdentityValidationError` | `MicroservicesError`, `ValueError` | `identity_validation` | A service or message identity is invalid |
| `HandlerCompilationError` | `MicroservicesError`, `ValueError` | `handler_compilation` | Handler metadata or signatures are invalid at startup |
| `WireValidationError` | `MicroservicesError`, `ValueError` | `wire_validation` | A wire value violates the transport-neutral contract |
| `WireEncodingError` | `WireValidationError` | `wire_encoding` | A value cannot be encoded under the wire contract |
| `WireDecodingError` | `WireValidationError` | `wire_decoding` | Bytes do not contain a valid wire envelope |
| `WireSizeLimitError` | `WireValidationError` | `wire_size_limit` | A wire value exceeds the configured message limits, checked before decoding |
| `WireDeadlineError` | `WireValidationError` | `wire_deadline` | An RPC request's timestamps are invalid, such as a `deadline_at` that is not later than `created_at` |
| `MessageInvocationError` | `MicroservicesError` | `invocation` | Base class for binding and pipeline failures while handling a message |
| `MessageConfigurationError` | `MessageInvocationError` | `invocation_configuration` | A handler or its result violates the message contract, such as an event handler returning a value |
| `MessageAuthorizationError` | `MessageInvocationError` | `authorization` | A message guard denied execution |
| `MessageRetryableError` | `MessageInvocationError` | `retryable` | Application code marks a failure as retryable |
| `MessageRejectedError` | `MessageInvocationError` | `rejected` | Application code rejects a message terminally |
| `PublicRpcError` | `MessageInvocationError` | `public_rpc` | Application code returns an error that may be shown to RPC callers; fields `code`, `public_message`, `retryable`, `details` |
| `TransportError` | `MicroservicesError` | `transport` | Base class for transport failures |
| `TransportUnavailableError` | `TransportError` | `transport_unavailable` | The transport cannot currently accept or deliver a publication |
| `TransportTimeoutError` | `TransportError` | `transport_timeout` | A transport operation exceeded the caller's deadline |
| `TransportRejectedError` | `TransportError` | `transport_rejected` | The transport rejected a publication before delivery |
| `TransportUnroutableError` | `TransportError` | `transport_unroutable` | A mandatory publication had no matching route |
| `TransportCapacityError` | `TransportError` | `transport_capacity` | A bounded in-memory queue or pending-reply map is full |
| `TransportStateError` | `TransportError` | `transport_state` | An operation is invalid in the transport's lifecycle state |
| `TransportCorrelationError` | `TransportError` | `transport_correlation` | A reply has no pending correlation or its correlation already completed |
| `TransportIndeterminateError` | `TransportError` | `transport_indeterminate` | The transport cannot determine whether an operation was accepted |
| `DuplicateSettlementError` | `TransportError` | `duplicate_settlement` | A delivery was acknowledged or rejected more than once |
| `RpcClientError` | `MicroservicesError` | `rpc_client` | Base class for client-side RPC outcomes |
| `UnknownServiceError` | `RpcClientError` | `unknown_service` | The requested service or contract version has no broker route |
| `RpcTimeoutError` | `RpcClientError` | `rpc_timeout` | The local RPC deadline passed before a reply arrived |
| `RpcProtocolError` | `RpcClientError` | `rpc_protocol` | A reply was malformed or its result failed to decode |
| `RpcOutcomeUnknownError` | `RpcClientError` | `rpc_outcome_unknown` | The client lost the reply path after publication became uncertain |
| `RemoteRpcError` | `RpcClientError` | `remote_rpc_error` | The remote service returned a stable typed error; fields `code`, `message`, `retryable`, `details` |
| `RabbitMqError` | `MicroservicesError` | `rabbitmq` | Base class for the RabbitMQ adapter |
| `RabbitMqConnectionError` | `RabbitMqError` | `rabbitmq_connection` | A connection or channel could not be acquired |
| `RabbitMqTopologyError` | `RabbitMqError` | `rabbitmq_topology` | A topology declaration failed or conflicts with broker state |

`PublicRpcError` is the explicit disclosure boundary. Its application-selected
`code`, `public_message`, `retryable`, and JSON-safe `details` may cross the wire.
Unexpected local exceptions never cross as Python module paths, tracebacks,
arguments, or representations; callers receive sanitized wire errors.
`RemoteRpcError` contains the stable public remote error, not the server's local
exception.

Distinguish transport outcomes:

- `TransportRejectedError` or `TransportUnroutableError` is definitive for that
  publication attempt.
- `TransportTimeoutError` describes a deadline at the local transport boundary.
- `TransportIndeterminateError` and `RpcOutcomeUnknownError` mean acceptance or
  remote execution may have occurred.
- `RpcTimeoutError` means the caller did not receive a reply before its deadline;
  it is not remote cancellation evidence.

The package never automatically resends accepted or indeterminate RPC. At-least-
once server execution means handlers and consumers need application-owned
idempotency.

## Persistent streams

`PersistentStreamsError` is the portable core base. The core types do not carry
diagnostic codes.

| Exception (`tori_py_persistent_streams_core`) | Base | Raised when |
| --- | --- | --- |
| `PersistentStreamsError` | `Exception` | Base class |
| `ValidationError` | `PersistentStreamsError`, `ValueError` | An input value violates its contract |
| `ResourceLimitError` | `ValidationError` | A stream, header, group-name, lease, or frame limit is exceeded |
| `InvalidPartitionError` | `ValidationError` | A partition is not an integer, is out of range, or a router returned an invalid partition |
| `UnknownStreamError` | `PersistentStreamsError`, `LookupError` | A stream name is not declared in the log |
| `IncompatibleStreamError` | `PersistentStreamsError` | A stream is declared again with a different definition, or existing broker topology does not match |
| `PublishingConflictError` | `PersistentStreamsError` | A named producer reuses a publishing ID for a different request |
| `StalePublishingIdError` | `PersistentStreamsError` | A named producer sends a publishing ID lower than the latest one already stored for it |
| `RetentionGapError` | `PersistentStreamsError` | Requested history is no longer retained; fields `stream`, `partition`, `requested_offset`, `requested_timestamp`, `bounds`, `group` |
| `OwnershipError` | `PersistentStreamsError` | A partition is already owned, or a checkpoint or cursor operation comes from a stale or non-current owner |
| `CheckpointError` | `PersistentStreamsError` | Base class for checkpoint failures |
| `CheckpointPersistenceError` | `CheckpointError` | Saving a checkpoint failed; fields `cursor`, `cause` |
| `CheckpointStrategyError` | `CheckpointError` | A group's checkpoint strategy is unsupported, changed, or incompatible with the deployment, such as broker-managed checkpoints with several replicas |
| `LifecycleError` | `PersistentStreamsError` | A log, producer, or consumer is used when closed, not accepting work, or busy |
| `PoisonRecordError` | `PersistentStreamsError` | Handling a record failed and stopped its partition; fields `stream`, `group`, `partition`, `offset`, `record_id`, `cause` |
| `AdapterContractError` | `PersistentStreamsError` | An adapter or checkpoint store returned a value outside its contract |

The core `LifecycleError` is a different class from `tori_py.LifecycleError`.
Import it from `tori_py_persistent_streams_core` when you catch it.

The ToriPy integration (`tori_py_persistent_streams`) adds stable codes:

| Exception | Base | Code | Raised when |
| --- | --- | --- | --- |
| `ToriPyPersistentStreamsError` | `Exception` | `tori_py_persistent_streams.error` | Base class |
| `StreamConfigurationError` | `ToriPyPersistentStreamsError` | `tori_py_persistent_streams.invalid_configuration` | Stream, binding, or runtime configuration is invalid |
| `StreamHandlerCompilationError` | `ToriPyPersistentStreamsError` | `tori_py_persistent_streams.invalid_handler` | Stream handler metadata or signatures are invalid |
| `StreamInvocationError` | `ToriPyPersistentStreamsError` | `tori_py_persistent_streams.invocation_failed` | One record cannot complete safely |
| `StreamRuntimeError` | `ToriPyPersistentStreamsError` | `tori_py_persistent_streams.runtime_failed` | Runtime lifecycle, admission, or adapter operation fails |
| `StreamPublicationSaturatedError` | `StreamRuntimeError` | `tori_py_persistent_streams.publication_saturated` | The runtime's publication admission bound is full |

The RabbitMQ adapter (`tori_py_persistent_streams_rabbitmq`) adds:

| Exception | Base | Raised when |
| --- | --- | --- |
| `RabbitMqPersistentStreamsError` | `PersistentStreamsError` | Base class for the adapter |
| `TopologyConflictError` | `RabbitMqPersistentStreamsError` | Existing Super Stream, partition, or binding topology conflicts with the declaration |
| `EnvelopeError` | `RabbitMqPersistentStreamsError`, `ValueError` | An AMQP message does not decode to a valid canonical envelope |

Useful bounded coordinates are exposed on errors such as:

- `RetentionGapError`: stream, partition, requested cursor or timestamp,
  available bounds, and optional group;
- `PoisonRecordError`: stream, group, partition, offset, record ID, and cause;
- `CheckpointPersistenceError`: attempted cursor when known and original cause.

The original `cause` is for local diagnosis. Do not serialize it to a public API
or place it unfiltered in logs. Payload bytes and headers are never diagnostic
labels.

The Tori Py integration adds stable `diagnostic_code` values through
`ToriPyPersistentStreamsError` and its configuration, handler compilation,
invocation, runtime, and publication-saturation subclasses. A failed decode,
handler, cleanup, or uncertain checkpoint stops the partition; filters may
observe an ordinary failure but cannot make the record checkpoint-eligible.

The RabbitMQ persistent-stream facade adds typed envelope and topology errors.
Publication and checkpoint uncertainty must remain unknown; the provisional
adapter must not turn disconnect into proof that no write occurred.

## Safe logging checklist

Prefer these fields when they are relevant and bounded:

- package diagnostic code and exception type;
- application, module, provider, route, scope, and lifecycle state;
- safe service, method, event, stream, partition, group, and schema aliases;
- UUID message, event, or record identities when application policy permits;
- outcome class, retryability class, phase, redelivery class, and error counts;
- latency and queue-depth buckets rather than unbounded values.

Exclude by default:

- request, RPC, event, or stream payloads;
- authorization, cookies, credentials, connection URLs, and secret settings;
- arbitrary headers and remote error text;
- member IDs, handles, content snippets, or other domain data as metric labels;
- exception `repr`, traceback, or nested causes at a public boundary.

Local secure exception logging may be appropriate for an application-owned
failure, but it is a separate policy from framework emergency diagnostics and
wire/HTTP disclosure.

## Testing failures

Tests should assert types, diagnostic codes, structured outcome fields, and
observable responses rather than complete implementation messages. For lifecycle
failures, also assert that started resources close and the application never
becomes ready. For indeterminate outcomes, assert that no automatic retry occurs.
For cancellation, assert cancellation identity or subtype is preserved.

Use `TestingModule` for framework composition and public provider replacement,
in-memory transports/stores/logs for deterministic semantic tests, and real
infrastructure tests for driver durability, topology, reconnect, TLS, and fault
behavior. Passing an in-memory or portable conformance suite does not establish
production infrastructure guarantees.
