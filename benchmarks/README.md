# Tori Py Competitor Benchmarks

This isolated project compares native-ASGI and Starlette-backed Tori Py with
raw ASGI, Starlette, FastAPI, and Litestar. It is excluded from the root release
workspace, so competitor dependencies cannot enter the published Tori Py
package family.

The suite reports measurements, not a universal framework ranking. Run it on
the hardware and container limits relevant to your deployment.

## Run

Build the pinned Python 3.14 image from the repository root:

```shell
docker compose -f benchmarks/compose.yaml build
```

Verify all applications and the measurement pipeline with a short run:

```shell
docker compose -f benchmarks/compose.yaml run --rm benchmark --smoke
```

Run the default suite:

```shell
docker compose -f benchmarks/compose.yaml run --rm benchmark
```

Results are written to `benchmarks/results/latest.json`. To retain separate
runs or change the workload:

```shell
docker compose -f benchmarks/compose.yaml run --rm benchmark \
  --duration 10 --warmup 3 --repeats 7 --startup-repeats 10 \
  --concurrency 1 16 64 --output /results/run-01.json
```

For development only, the same pipeline can run on the host:

```shell
uv run --project benchmarks tori-py-benchmark \
  --smoke --output benchmarks/results/local-smoke.json
```

Capture a deterministic Linux CPU profile for one Tori Py workload:

```shell
docker compose -f benchmarks/compose.yaml run --rm benchmark \
  --duration 5 --warmup 1 --repeats 2 \
  --profile-scenario plaintext --profile-concurrency 16 \
  --profile-output /results/tori-asgi-plaintext.pstats \
  --output /results/tori-asgi-plaintext-profile.json
```

The raw `cProfile` data and a top-40 cumulative text summary are written beside
the JSON report. Profiling intentionally runs only native-ASGI Tori Py and is
diagnostic; its instrumented throughput must not be compared with normal
benchmark runs.

## Workloads

Every framework exposes the same GET routes:

| Route | Response | Purpose |
| --- | --- | --- |
| `/health` | `{"status":"ok"}` | Readiness only; not timed as a scenario |
| `/plaintext` | `Hello, World!` | Minimal response path |
| `/json` | `{"message":"Hello, World!"}` | Native JSON serialization path |
| `/singleton` | `{"value":5}` | Prebuilt singleton-chain access; renamed from the former `/di` scenario |
| `/inject` | `{"value":5}` | Resolve a five-level dependency chain at route time |

`/singleton` preserves the prior `/di` workload under an accurate name: it is
only access through a prebuilt or singleton chain, not route-time resolution.
`/inject` isolates route-time resolution. FastAPI uses nested `Depends`,
Litestar uses nested `Provide` providers and `NamedDependency` parameters, and
Both Tori Py adapters resolve request-scoped providers from an
`Annotated[..., Inject(...)]` handler parameter. Raw ASGI and Starlette have no
DI container, so their `/inject` control explicitly constructs the chain once
per request.

No Tori-only transport, scope, or pipeline diagnostic routes are included in
the competitor report. The public HTTP route contract can exercise request
scope resolution through `/inject`, but does not expose separate transport or
pipeline-isolation measurements without coupling the benchmark to production
internals.

## Method

- All frameworks run from one image and one `uv.lock`.
- Every server is a separate one-worker Uvicorn process.
- Every server uses `asyncio`, `httptools`, lifespan handling, no access log,
  and no server header.
- Both Tori Py adapters preserve the framework's `X-Request-ID` behavior. The
  competitor controls do not add an equivalent header, so use the two Tori Py
  rows, rather than cross-framework rows, to isolate adapter overhead.
- A correctness preflight checks status and body before timing each framework.
- Locust `FastHttpUser` generates HTTP/1.1 keep-alive load over container
  loopback from an isolated local-runner process. Each Locust user issues at
  most one request at a time.
- Locust statistics are reset after all users spawn, so warmup and ramp-up data
  are discarded. Reported throughput is total completed requests divided by
  the configured measurement time across repeats.
- Framework order rotates deterministically for every scenario/concurrency cell
  to distribute host and thermal drift instead of grouping all work by framework.
- p50, p95, and p99 are calculated from the combined Locust response-time
  histograms. Errors are reported as a subset of completed requests.
- The duration is a hard measurement deadline. Requests still in flight at the
  deadline are stopped and excluded from the captured statistics.
- Cold startup measures process creation through successful `/health`
  readiness, including imports, framework initialization, route compilation,
  and ASGI lifespan startup.
- Point-in-time RSS is read from Linux `/proc` after readiness and at the end of
  each framework's HTTP workloads. It is not peak RSS and is unavailable for
  host runs on platforms without `/proc`.

The raw-ASGI result is a lower-bound control. If multiple frameworks converge
on raw-ASGI throughput, Locust or the available CPU may be saturated; use a
distributed or external native load generator before drawing conclusions.
Compose limits the benchmark to two CPUs and 2 GiB of memory, and the effective
cgroup limits are recorded in the report. Do not compare results captured with
different limits, host power modes, or background workloads.

## Report

The JSON report includes runtime versions, base-image identity, lock/source
hashes, cgroup limits, host/container metadata, configuration, startup samples,
HTTP summaries, per-run throughput, errors, point-in-time RSS, and derived
comparisons.

`tori_py_rps_difference_percent` is positive when native-ASGI Tori Py completes
more requests per second than the named framework, including Starlette-backed
Tori Py. The p95 latency difference uses the same arithmetic, so a negative
`tori_py_p95_latency_difference_percent` means native-ASGI Tori Py has lower
latency.

## Verify

```shell
uv run --project benchmarks pytest -c benchmarks/pyproject.toml benchmarks/tests -q
uv run --project benchmarks ruff check benchmarks
uv run --project benchmarks ruff format --check benchmarks
uv run --project benchmarks ty check benchmarks/src benchmarks/tests
```

The framework DI implementations follow their public documentation:

- [FastAPI dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [Litestar dependency injection](https://docs.litestar.dev/latest/usage/dependency-injection.html)
- [Starlette routing](https://www.starlette.io/routing/)
- [ASGI specifications](https://asgi.readthedocs.io/en/latest/specs/index.html)
- [Uvicorn lifespan](https://uvicorn.dev/concepts/lifespan/)
- [Locust as a library](https://docs.locust.io/en/stable/use-as-lib.html)
- [Locust FastHttpUser](https://docs.locust.io/en/stable/increase-performance.html)
