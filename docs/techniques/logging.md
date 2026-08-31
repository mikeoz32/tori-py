# Logging And Correlation

ToriPy exposes a driver-neutral `Logger` protocol and an opt-in
`LoggingModule`. The default `PythonLogger` delegates to the standard-library
`logging` package and stores structured fields in a `tori_py` attribute on each
`LogRecord`.

## Register The Logger

Import one configured logging module into the application graph:

```python
from tori_py import Logger, module
from tori_py.logging import LoggingModule


logging_module = LoggingModule.for_root(
    application="orders-api",
    logger_name="orders-api",
)


@module(imports=[logging_module])
class AppModule:
    pass
```

`LoggingModule.for_root()` exports `Logger`. It is global by default, but normal
module visibility still applies if `global_=False`. Its provider is a singleton
`PythonLogger` with the configured `application` field. `logger_name` selects a
Python logger and `level` sets that logger's threshold.

The module does not install handlers, choose stdout or stderr, configure
propagation, define retention, or install a text or JSON formatter. Configure
Python logging in the process entry point or deployment logging layer before
application startup. Formatters must tolerate records from ToriPy, Starlette,
Uvicorn, and application libraries that do not all contain the same custom
attributes.

## Structured Records

The protocol supports `debug`, `info`, `warning`, `error`, and immutable
binding:

```python
class OrderService:
    def __init__(self, logger: Logger) -> None:
        self._logger = logger.bind(component="order-service")

    def accepted(self, order_id: str) -> None:
        self._logger.info("Order accepted", order_id=order_id)
```

For that call, `record.getMessage()` is `Order accepted` and
`record.tori_py` is a mapping such as:

```python
{
    "application": "orders-api",
    "component": "order-service",
    "order_id": "order-123",
    "request_id": "request-456",
    "scope": "request",
}
```

`bind()` returns a new logger and does not mutate the original. Fields are
combined in this order:

1. ambient correlation context;
2. fields already bound to the logger;
3. fields on the individual log call.

Later application fields replace earlier application fields, except for
framework-reserved names. The reserved names are:

```text
application
module
provider
route
scope
request_id
resource_state
```

`bind()` and log calls silently discard user values for those names, so
application code cannot overwrite framework correlation. Use names such as
`component`, `operation`, `entity_id`, or `tenant_id` for application data.

The structured mapping is not automatically serialized. A production formatter
or log shipper must read `record.tori_py`, merge it into the chosen event schema,
and define behavior for ordinary records where the attribute is absent.

## Correlation Context

`use_log_context()` stores immutable ambient fields in a `ContextVar`, merges
nested contexts, and restores the previous context in `finally`:

```python
from tori_py.logging import current_log_context, use_log_context


with use_log_context(operation="rebuild-index"):
    fields = current_log_context().fields
```

This primitive is useful for framework integrations and bounded application
operations. Context variables follow normal Python async-task propagation: a
new task usually receives a copy of its creator's current context. Do not create
detached tasks from a request and assume request correlation or request-scoped
dependencies will remain valid. `WorkScopeFactory.run()` deliberately executes
with a fresh context for background work; establish new operation correlation
inside that operation.

## HTTP Request IDs

For each Starlette HTTP request, ToriPy establishes ambient fields for the
application identity, `scope="request"`, and `request_id`. The context remains
available through request-scope cleanup and through a native Starlette response's
transmission and `BackgroundTask`. It is reset after the complete ASGI response
and request cleanup.

The inbound `X-Request-ID` policy is:

- exactly one value matching `[A-Za-z0-9._-]{1,128}` is accepted;
- a missing ID produces a generated UUID;
- an invalid, non-ASCII, oversized, or duplicate ID is replaced;
- the warning does not echo rejected input;
- the selected ID is exposed through HTTP context and response `X-Request-ID`;
- framework response handling overwrites an application-supplied `X-Request-ID`.

A request ID is untrusted observability metadata. It is not an identity,
credential, idempotency key, or authorization signal. If a reverse proxy needs
authoritative IDs, it must remove client values and inject one trusted value
before forwarding.

The current automatic `PythonLogger` context contains request-level
`application`, `request_id`, and `scope` fields. The other reserved names support
framework or integration context, but application code must not assume that
every record automatically contains module, provider, route, or resource-state
fields.

## Failure Diagnostics

Ordinary application logs use the configured `Logger`. Internal framework
lifecycle and transport diagnostics can also be emitted directly through Python
logging namespaces such as `tori_py.starlette` and
`tori_py.http.pipeline`; configure those namespaces as part of the process log
policy.

When response transmission or emergency error rendering has already failed,
ToriPy emits a sanitized event containing a fixed event code and a newly
generated event ID. That boundary deliberately omits request values, the caller
request ID, exception text, representations, and traceback. Other lifecycle
logs may contain operational exception information, so production access to
logs still needs normal controls.

`Secret[T]` does not automatically sanitize application log calls. Never bind a
settings object, credential, authorization header, cookie, request body, or
arbitrary object representation without an application-owned allowlist and
redaction policy.

## Operational Checklist

- Configure handlers and formatting before application startup.
- Emit structured output to stdout/stderr in containers and let the platform handle rotation.
- Preserve `tori_py` fields in the formatter or shipper.
- Configure Uvicorn access logs separately; `LoggingModule` does not replace them.
- Keep request IDs searchable but never trust them for security decisions.
- Use stable application event names and bounded scalar fields rather than payload dumps.
- Alert on startup failure, `lifecycle.lingering_task`, `resource.lingering_resource`, and repeated sanitized HTTP emergency events.
- Add tracing, metrics, sampling, and OpenTelemetry through application-owned integrations; ToriPy does not install them.
