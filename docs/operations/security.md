# Security

ToriPy secures specific framework boundaries, but it is not an application
security product. Authentication, authorization policy, secret management,
network hardening, and deployment controls remain application and operator
responsibilities unless an independently installed package explicitly says
otherwise.

## Responsibility Matrix

| Concern | ToriPy behavior | Application or operator responsibility |
| --- | --- | --- |
| Dependency graph | Validates explicit visibility, cycles, aliases, and scope paths before serving | Register only trusted providers and factories |
| Settings errors | Uses value-free framework diagnostics and rejects secret CLI paths | Protect source files/environment and redact custom decoder failures |
| YAML | Uses `yaml.safe_load` | Treat configuration as privileged input and restrict file access |
| HTTP errors | Default unexpected failures become 500 Problem Details without client tracebacks | Review custom filters and native responses for disclosure |
| Request IDs | Validates syntax, rejects duplicates, replaces unsafe values | Treat IDs as untrusted metadata and define proxy policy |
| Parsed JSON body | Enforces `StarletteOptions.body_size_limit` while reading | Add edge limits for every connection/request dimension |
| Raw body stream | Enforces each route's `BodyStream(max_bytes=...)` | Select a finite route limit and process content safely |
| Cancellation | Does not let exception filters convert `BaseException` cancellation/system exits | Make handlers and lifecycle hooks cancellation-safe |
| Authentication and authorization | Supplies guard extension points only | Implement and test identities, credentials, sessions, and policy |
| Transport security | None | Configure TLS and trusted proxy/network boundaries |
| Browser security | No CORS, CSRF, or security-header policy | Configure according to the application's trust model |

## Secrets And Configuration

`Secret[T]` marks settings paths for framework redaction policy and rejects those
paths from CLI `--set`. CLI rejection uses `<redacted>` and does not echo the
value. Secrets may be loaded from explicit files, dotenv, or environment.

This is not encryption or a secret store. The decoded field is an ordinary
runtime value, and application code can still expose it through logging,
serialization, exceptions, debugging, or object representations. Apply these
controls:

- use a platform secret manager, protected process environment, or read-only mounted file;
- restrict filesystem and deployment-metadata access;
- rotate credentials independently of request IDs and application releases;
- never put secrets in `--set`, image layers, source control, probe output, or command arguments;
- do not log complete settings objects or arbitrary provider representations;
- require custom codecs/decoders to raise value-free diagnostics;
- keep development dotenv files out of production images and source control.

Unknown environment keys are ignored. Validate deployment variable names so a
misspelling cannot silently leave a non-secret default in use.

## Authentication And Authorization

ToriPy does not authenticate callers or ship authorization policy. Guards are an
execution extension point, not a built-in identity system. An application must
define:

- credential transport and validation;
- principal construction and request-scoped access;
- route and object-level authorization;
- key rotation, revocation, expiry, and clock policy;
- safe 401/403 behavior and audit events;
- protection against replay where the protocol requires it.

A guard returning `False` maps to 403, but the framework cannot decide whether a
request should be 401, which identity is trusted, or which resource it may
access. OpenAPI security metadata, if an optional package is used, documents a
scheme and does not install authentication.

## Browser And Edge Controls

The core framework does not provide CORS, CSRF, rate limiting, host-header
validation, HSTS, content-security policy, other security headers, or TLS.
Configure these at a trusted reverse proxy or through an explicitly reviewed
application integration.

When cookies carry credentials, define `Secure`, `HttpOnly`, and `SameSite`
policy and add CSRF protection appropriate to the request model. CORS is not an
authorization boundary. Validate allowed hosts and forwarding headers before
using request scheme, host, or client information in security decisions.

Only trust proxy headers from known proxy addresses. Strip client-supplied
forwarding headers at the edge. ToriPy's `X-Request-ID` validation does not make
the value trusted.

## Input Limits And Parsing

The default `StarletteOptions.body_size_limit` is 1 MiB and may be set to zero.
It applies while ToriPy reads a parsed `Body()` JSON request and while enforcing
an opt-in `@no_body` route. It uses actual received bytes, not `Content-Length`.

`BodyStream(max_bytes=...)` has an independent route-specific limit. The global
JSON limit does not apply to that stream. A stream is single-consumer,
request-lifetime, directly backpressured, and must be consumed through the final
request message before a successful response. ToriPy neither parses nor spools
it.

Important gaps require edge controls:

- routes without `Body()`, `BodyStream()`, or `@no_body` do not establish a framework-wide total-body policy;
- header count/size, request-line size, query complexity, connection count, and slow-client behavior are not limited by `StarletteOptions`;
- decompression bombs and application-level JSON depth/cardinality need deliberate controls;
- multipart, form, and file parsing are not framework-managed APIs;
- a server controls ASGI message sizes below ToriPy's receive boundary.

Set finite proxy/server limits before traffic reaches the application. Validate
domain sizes after decoding, and never allocate based only on an untrusted
declared length.

## Errors And Logs

Default HTTP failures use RFC 9457 Problem Details. Unexpected exceptions return
a generic 500 detail without a source traceback. Sanitized emergency logging
after response/error-rendering failure includes only a fixed event code and a
fresh event ID, not the caller request ID, request values, exception text, or
traceback.

Custom exception filters, native Starlette responses, codecs, application logs,
and proxy error pages can weaken those guarantees. Review them for:

- stack traces, SQL, paths, hostnames, and dependency topology;
- authorization headers, cookies, tokens, and settings values;
- reflected request IDs or payload fragments;
- stable internal identifiers that enable enumeration;
- different error timing or detail that leaks authorization state.

Framework lifecycle logs may contain operational exception information and need
restricted access and retention. Do not configure a formatter that dumps all
`LogRecord` or exception object attributes indiscriminately.

## Request IDs

One inbound ASCII ID matching `[A-Za-z0-9._-]{1,128}` is accepted and returned.
Missing or invalid/duplicate input is replaced. Unsafe rejected input is not
echoed in the warning.

The accepted value can still be attacker-chosen. Do not use it as:

- a user or service identity;
- proof that a trusted proxy handled the request;
- an idempotency or deduplication key;
- a database authorization key;
- a trace sampling command without validation and limits.

When authoritative edge correlation is required, remove client values and set
exactly one generated ID at the trusted proxy.

## Cancellation And Shutdown

Pipeline filters catch `Exception`, not `asyncio.CancelledError`,
`KeyboardInterrupt`, `SystemExit`, or other `BaseException` values. Stale
request resolvers fail after scope closure. These rules prevent ordinary error
handling from reviving cancelled requests or using closed request dependencies.

Application code must still:

- preserve cancellation rather than converting it to success;
- put cleanup in context managers or `finally` blocks;
- avoid detached tasks that retain request context or credentials;
- stop subsystem intake in `on_application_quiesce`;
- bound downstream calls and cooperate with the shutdown deadline;
- design retries, idempotency, and transaction semantics for interrupted work.

A hard process kill, cancellation-resistant coroutine, or blocked executor
thread can outlive the framework deadline. External systems must remain safe
under partial execution.

## Dependencies And Reporting

Use the application lock file, review transitive dependencies and optional
extras, and rebuild artifacts when security fixes are released:

```text
uv lock --check
```

The project is beta. Before the first public release, fixes target the current
default branch; afterward, the latest minor of each independently versioned
package is supported, and older `0.x` minors are not guaranteed fixes.

Do not report suspected vulnerabilities in a public issue. Follow the root
`SECURITY.md` policy and use GitHub private security advisory reporting. Include
affected package versions, impact, and safe reproduction steps without real
credentials, personal data, or production payloads.

## Security Checklist

- Secrets are absent from CLI arguments, images, source, logs, probes, and error bodies.
- Authentication and route/object authorization have explicit tests.
- Proxy trust, TLS, allowed hosts, CORS, CSRF, rate limits, and security headers are configured at reviewed layers.
- Network and domain limits cover inputs not bounded by ToriPy's JSON or stream limits.
- Request IDs are treated as untrusted metadata.
- Custom filters and native responses do not expose tracebacks or sensitive details.
- Cancellation, timeout, retry, idempotency, and partial-execution behavior are tested.
- Logs and diagnostics have access control, retention, alerting, and redaction.
- Locked dependencies and independently versioned optional packages are included in vulnerability review.
- The deployed proxy, probes, graceful shutdown, and hard-kill behavior have been exercised outside in-process tests.
