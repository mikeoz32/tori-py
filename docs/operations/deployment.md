# Deployment

Deploy the exported `asgi(create_application)` callable through an ASGI server
with lifespan enabled. ToriPy provides application lifecycle semantics, not a
process manager, reverse proxy, container platform, or Kubernetes integration.

## Baseline Server Command

Use direct Uvicorn when deployment needs an externally reachable bind or server
options:

```text
uv run uvicorn myapp:application --host 0.0.0.0 --port 8000 --lifespan on
```

Declare `tori-py-framework[cli]` as an application dependency when the image
runs Uvicorn, commit the application lock file, and install production
dependencies from that lock:

```text
uv sync --locked --no-dev
```

Do not call the async application factory directly from a process manager. The
import target is the synchronous ASGI wrapper exported by `asgi()`.

## Reverse Proxies

Terminate public TLS at a trusted edge or configure it explicitly in the ASGI
server. Forward to a private application listener and define all proxy trust
from the actual network topology.

ToriPy does not interpret `Forwarded`, `X-Forwarded-For`,
`X-Forwarded-Proto`, or `X-Forwarded-Host`. Configure Uvicorn's proxy-header
handling and trusted forwarding addresses directly when those values must affect
the ASGI scope. Never trust forwarded headers from arbitrary clients. Strip
untrusted forwarding headers at the edge and allow only known proxy addresses.

`X-Request-ID` has a separate ToriPy policy. Exactly one syntactically safe
client value is accepted, but a safe value is still untrusted. Choose one edge
policy:

- preserve a safe inbound value for end-to-end correlation; or
- remove all client values and inject one edge-generated value when the ID must be authoritative.

Do not append a second `X-Request-ID`; duplicate fields cause ToriPy to replace
the input. Never use the selected ID for authentication, authorization, or
idempotency.

The edge should also own limits that ToriPy does not apply globally: connection
counts, header size/count, request-line size, slow clients, total request size,
timeouts, and rate limits. Align edge timeouts with legitimate streaming and
shutdown behavior rather than relying on application cancellation alone.

If the application is mounted under a path prefix, verify the proxy's path and
ASGI root-path behavior against the pinned Starlette and Uvicorn versions.
ToriPy does not add a deployment-prefix API.

## Containers

Use an exec-form command so Uvicorn receives termination signals directly. A
Containerfile command can use the locked project environment:

```dockerfile
CMD ["uv", "run", "--no-sync", "uvicorn", "myapp:application", "--host", "0.0.0.0", "--port", "8000", "--lifespan", "on"]
```

Container guidance:

- run as a non-root user and grant only required filesystem access;
- keep the image and lock file immutable;
- deliver secret files through read-only mounts or the platform secret mechanism;
- write logs to stdout/stderr and let the platform ship and retain them;
- use one process per container unless measured capacity requires multiple Uvicorn workers;
- if workers are used, count every worker's singleton resources and connection pools;
- do not persist application state in the container filesystem or process memory when replicas must share it;
- use an exec form rather than a shell wrapper that can swallow `SIGTERM`;
- leave enough termination time for server connection drain and ToriPy shutdown.

The convenience `tori-py run` command has no host flag and uses Uvicorn's
loopback default, so direct Uvicorn is the practical container path.

## Kubernetes Probes

ToriPy does not create health routes. Implement ordinary application
controllers for the probes and define their policy in application providers.
Typical endpoint names are illustrative, not framework APIs:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: application
spec:
  selector:
    matchLabels:
      app: application
  template:
    metadata:
      labels:
        app: application
    spec:
      terminationGracePeriodSeconds: 45
      containers:
        - name: application
          image: registry.example/tori-py-application:release
          ports:
            - containerPort: 8000
          startupProbe:
            httpGet:
              path: /livez
              port: 8000
          livenessProbe:
            httpGet:
              path: /livez
              port: 8000
          readinessProbe:
            httpGet:
              path: /readyz
              port: 8000
```

Select thresholds from measured startup and recovery time. A startup probe can
prevent liveness from killing a process while slow singleton resources are
being acquired.

### Liveness

Liveness answers whether the process and event loop should be restarted. Keep
it local and cheap. Do not make liveness depend on a database, broker, remote
service, or another replica; an external outage should not trigger a restart
storm.

### Readiness

Readiness answers whether this replica should receive new traffic. It may depend
on application-owned status for required downstream systems, warmed state, or
subsystems. Return a non-success status when the replica cannot safely handle
normal work.

ASGI startup itself is a readiness barrier: until the factory, eager providers,
route binding, and bootstrap hooks complete, the wrapper does not delegate HTTP
and returns 503. Startup readiness does not provide ongoing dependency health.
Applications and optional integrations must track post-start degradation
explicitly.

Do not expose sensitive dependency details, credentials, topology, or exception
text in probe bodies. Operators need a status and separate protected diagnostics.

During framework shutdown, request admission closes before quiescence. Existing
connections may drain, but new ToriPy request scopes are rejected. Coordinate
endpoint removal, server signal handling, and load-balancer propagation; do not
assume a readiness response remains available after termination starts.

## Graceful Shutdown

`ApplicationOptions` controls the framework's one shared shutdown budget:

```python
from tori_py import ApplicationOptions, NestApplication
from tori_py.starlette import StarletteAdapter


application = await NestApplication.create(
    AppModule,
    options=ApplicationOptions(
        shutdown_timeout=30.0,
        cancellation_grace=1.0,
        cleanup_reserve=5.0,
    ),
    adapter=StarletteAdapter(),
)
```

For shutdown to remain bounded, all values must be finite and non-negative, and
`cancellation_grace + cleanup_reserve <= shutdown_timeout` must hold. Defaults
are 30, 1, and 5 seconds. The current validator does not yet reject every
non-finite value: `float("nan")` and positive infinity can pass validation.
This is a validation gap, not a supported configuration; do not use non-finite
budgets.

On ASGI shutdown, ToriPy:

1. closes new request admission;
2. runs `on_application_quiesce(context)` in reverse bootstrap order while application work scopes are still available;
3. closes work-scope admission;
4. drains active request and work scopes until the reserved cutoff;
5. cancels remaining owner/user tasks and observes them for `cancellation_grace`;
6. runs shutdown hooks, closes the adapter, runs destroy hooks, and closes resources within the remaining deadline;
7. preserves the first failure while continuing cleanup where safe;
8. logs work or resources that remain open after the deadline and returns without unbounded cleanup.

Use `on_application_quiesce(context)` for lifecycle-managed non-HTTP consumers
to stop intake and drain accepted work. The hook is async, receives one
`ShutdownContext`, and must cooperate with cancellation. Do not begin new
unbounded work during quiescence.

ToriPy cannot force a cancellation-resistant coroutine to finish or stop a
synchronous context-manager call already running in an executor thread. Bounded
shutdown is best effort after the deadline, with diagnostics for lingering
work.

The platform's outer termination grace must exceed all layers that run before
process exit: load-balancer removal or `preStop`, Uvicorn connection/task drain,
ToriPy's `shutdown_timeout`, and a safety margin. Configure Uvicorn's graceful
timeout directly and test the complete signal path under active requests. If an
outer supervisor sends `SIGKILL` first, no framework can complete cleanup.

## Rolling Deployments And Workers

Every replica and Uvicorn worker is an independent application. Startup hooks,
migrations mistakenly placed in startup, and singleton side effects run once per
process. Keep deployment-wide migrations and one-time administrative work
outside application startup unless the operation is explicitly safe under
concurrent replicas.

Use readiness to add a new replica only after successful startup. Use deployment
surge/unavailable settings that preserve required capacity while old replicas
drain. Persist shared state externally, and use application-level idempotency or
coordination where work may be retried.

## Production Checklist

- The runtime satisfies Python `>=3.14,<3.15`, and the beta package version is pinned and tested.
- The application exports `application = asgi(create_application)` and the factory returns an unstarted app with a fresh `StarletteAdapter`.
- Uvicorn is invoked through `uv`, with `--lifespan on`, explicit bind settings, and reviewed timeout/proxy/log options.
- The lock file is current, immutable in the image, and installed with `uv sync --locked --no-dev`.
- Startup failure prevents readiness and is visible in alerts.
- Liveness is local; readiness reflects whether the replica can safely accept normal traffic.
- Reverse-proxy trust is restricted to known addresses; untrusted forwarded headers are stripped.
- TLS, host validation, CORS, CSRF, rate limits, security headers, and authentication are implemented at deliberate layers.
- Network limits complement `StarletteOptions.body_size_limit` and route-specific `BodyStream` limits.
- Secrets come from protected environment or read-only files, never `--set`; logs do not serialize settings or payloads.
- Structured application fields and ToriPy lifecycle/emergency namespaces reach the log backend.
- Request IDs are searchable but never trusted as security or idempotency data.
- Worker/replica counts are included in database, broker, file-descriptor, and downstream capacity calculations.
- `ApplicationOptions` and the outer termination grace are aligned and tested with active requests and non-HTTP work.
- Quiesce hooks stop subsystem intake, cooperate with cancellation, and do not start unbounded cleanup.
- Migrations and one-time jobs are not accidentally executed by every worker.
- In-process testing is supplemented by a deployed smoke test through the real proxy, TLS, probes, and signal path.
- Alerts cover startup failure, readiness degradation, shutdown failure, lingering work/resources, elevated 5xx, and sanitized emergency events.
- The [security guide](security.md) and [limitation matrix](limitations.md) have been reviewed for the deployed feature set.
