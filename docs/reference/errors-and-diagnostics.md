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

Principal framework families are `BootstrapError`, `ResolutionError`,
`ScopeError`, `ResourceError`, `LifecycleError`, `SettingsError`,
`PipelineStateError`, and `ApplicationStateError`. `DIAGNOSTIC_CODES` inventories
the stable graph, settings, testing, resource, lifecycle, and application codes
used by framework diagnostics, such as `provider.unresolved`,
`provider.ambiguous`, `provider.scope_violation`, `route.duplicate`,
`settings.decode_error`, and `lifecycle.shutdown_timeout`.

Prefer code-based handling over matching message text:

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

## Settings, SQLAlchemy, and OpenAPI

SQLAlchemy and OpenAPI integration errors inherit `ToriPyError`, so they expose
the same diagnostic contract:

| Family | Base and principal errors | Meaning |
| --- | --- | --- |
| SQLAlchemy | `SqlAlchemyIntegrationError`, `SqlAlchemyConfigurationError`, `TransactionContextError` | Invalid module options or unsafe use of inherited/escaped transaction context |
| OpenAPI | `OpenApiError`, `OpenApiConfigurationError`, `OpenApiMetadataError`, `OpenApiSchemaError` | Invalid options, metadata, or unsupported schema compilation |

These errors generally fail compilation or startup. Do not convert them into a
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

`tori_py_cqrs_core.CqrsError` is the framework-neutral base. Its subclasses
separate validation, duplicate or missing handlers, nested command dispatch,
queue capacity, caller timeout, reply correlation, and transport lifecycle.
These exceptions do not expose the framework `Diagnostic` object; handle their
types and documented fields.

`tori_py_cqrs.ToriPyCqrsError` adds integration configuration, lifecycle,
pipeline, and handler-exit failures. `CqrsHandlerExitError` retains the body error
and callback errors. `CqrsHandlerExitCancellationError` preserves cancellation.

For an accepted in-memory command or query, caller timeout or cancellation stops
waiting but does not necessarily cancel worker-owned handling. Never infer
rollback from `RequestTimeoutError` alone.

## Event sourcing

Event-sourcing core has typed families for aggregate lifecycle, schema and codec,
EventStore, repository, Unit of Work, optimistic concurrency, duplicate event
IDs, and resource limits.

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

`MicroservicesError` subclasses have a stable class-level `diagnostic_code`.
Important groups include:

- Identity, wire validation, encoding, decoding, size, and deadline errors.
- Handler compilation, authorization, invocation, explicit retry, and terminal
  rejection errors.
- Transport unavailable, timeout, rejected, unroutable, capacity, state,
  correlation, and indeterminate errors.
- RPC unknown-service, timeout, protocol, remote-error, and outcome-unknown
  errors.
- RabbitMQ connection and topology errors.

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

`PersistentStreamsError` is the portable core base. Typed errors separate input
validation and limits, unknown or incompatible streams, partition errors,
publishing conflicts, stale publishing IDs, retention gaps, ownership, checkpoint
persistence, lifecycle, poison records, and adapter contract violations.

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
