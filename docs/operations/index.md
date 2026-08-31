# Operations

ToriPy separates application composition from process serving. An async
application factory creates an unstarted `NestApplication`; an ASGI lifespan
owner starts it once, serves only after successful startup, and shuts it down
once.

Choose a serving path deliberately:

| Need | Path |
| --- | --- |
| Local run with defaults and non-secret `--set` overrides | [`tori-py run`](cli-and-asgi.md#tori-py-run) |
| Host, port, workers, reload, proxy trust, TLS, or server logging options | [Export an ASGI wrapper and run Uvicorn directly](cli-and-asgi.md#direct-uvicorn) |
| Reverse proxy, container, or Kubernetes deployment | [Deployment](deployment.md) |
| Threat boundaries and hardening responsibilities | [Security](security.md) |
| Supported and deliberately absent behavior | [Limitations](limitations.md) |

Operational techniques used by these pages are documented separately:

- [Settings](../techniques/settings.md)
- [Logging and correlation](../techniques/logging.md)
- [Testing applications](../techniques/testing.md)

## Lifecycle Contract

Production hosting must enable ASGI lifespan. Before startup completes, the
wrapper has no HTTP application and returns 503 Problem Details. On startup
failure, lifespan reports failure and the process must not receive traffic. On
normal termination, the ASGI server must send lifespan shutdown and allow the
framework's bounded cleanup to complete.

The wrapper and its `StarletteAdapter` are single-use. Every process, worker,
and reload generation imports the target and creates a fresh application. There
is no shared in-process singleton state between workers.

## Operator Responsibilities

ToriPy owns graph validation, provider resources, request/work scopes,
lifecycle hooks, request IDs, and a bounded internal shutdown. The deployment
owns:

- server process configuration and supervision;
- TLS and trusted reverse-proxy configuration;
- authentication and authorization policy implementations;
- CORS, CSRF, host validation, rate limits, and security headers;
- health endpoints and the meaning of dependency readiness;
- secret delivery and log redaction outside framework diagnostics;
- network-level request limits and denial-of-service controls;
- worker count, capacity, rollout, and outer termination deadlines;
- metrics, traces, alerts, log shipping, retention, and incident response.

Use the [production checklist](deployment.md#production-checklist) before a
release and review the [limitation matrix](limitations.md) whenever an
application relies on behavior outside the core framework.
