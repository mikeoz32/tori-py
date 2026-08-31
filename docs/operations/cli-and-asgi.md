# CLI And ASGI Hosting

ToriPy supports one convenience server command and one general ASGI deployment
shape. Both use the same `asgi()` lifespan wrapper; they differ in who owns
Uvicorn configuration.

## Application Shape

An HTTP factory must be an `async def`, return an unstarted
`NestApplication`, and select a fresh `StarletteAdapter`:

```python
from tori_py import NestApplication
from tori_py.starlette import StarletteAdapter, asgi


async def create_application() -> NestApplication:
    return await NestApplication.create(
        AppModule,
        adapter=StarletteAdapter(),
    )


application = asgi(create_application)
```

Do not call `application.start()` in the factory. The ASGI wrapper starts the
application during `lifespan.startup` and shuts it down during
`lifespan.shutdown`.

## Installation

The CLI extra installs Uvicorn without making it an eager base-package import:

```text
uv add 'tori-py-framework[cli]'
```

Importing `tori_py` or `tori_py.cli`, and displaying help or version, does not
load Uvicorn.

## `tori-py run`

The only serving command is:

```text
uv run tori-py run myapp:create_application
```

The target must use `module:attribute` form. The current working directory is
made importable if needed. The attribute must exist, be callable, and be
recognized by `inspect.iscoroutinefunction()` as an async function. The wrapper
later performs the authoritative checks that calling it returns an awaitable and
that awaiting it yields a `NestApplication` using `StarletteAdapter`.

Add non-secret settings overrides after the target:

```text
uv run tori-py run myapp:create_application --set service.name=worker-a --set database.port=6432
```

`--set` may be repeated. It splits on the first `=`, requires a non-empty path,
keeps the value as text, and uses the final value for a duplicate path.
`SettingsModule` rejects unknown paths and paths marked `Secret[T]` during
startup. Rejected secret values are not echoed.

The command builds a `BootstrapContext`, wraps the factory so that context stays
active while deferred settings modules materialize in Uvicorn's event loop, and
then calls:

```python
uvicorn.run(application, lifespan="on")
```

It does not compile or await the factory in a separate event loop.

## Exact CLI Limits

`tori-py run` intentionally has a narrow surface:

| Capability | CLI behavior |
| --- | --- |
| Serving command | `run` only |
| Target | Async `module:factory` only |
| Settings arguments | Repeated non-secret `--set PATH=VALUE` only |
| ASGI lifespan | Forced on |
| Server | Uvicorn only |
| Host and port | No flags; Uvicorn defaults apply |
| Reload | No flag |
| Worker processes | No flag |
| Proxy-header trust | No flags |
| TLS certificates | No flags |
| UDS or file descriptor | No flags |
| Server timeouts and limits | No flags |
| Uvicorn log configuration | No flags |
| Arbitrary Uvicorn passthrough | Not supported |
| Sync factory or prebuilt ASGI target | Rejected |

The current Uvicorn defaults bind to loopback port 8000. Because the CLI cannot
change that binding or configure proxy trust and shutdown settings, use it for
local and deliberately defaulted runs. Use direct Uvicorn for containers and
production server configuration.

CLI import/target errors exit through the argument parser without a traceback.
Factory, settings, startup, or shutdown errors happen under ASGI lifespan and
are reported by the server as lifespan failures.

## Direct Uvicorn

Export `application = asgi(create_application)` and give Uvicorn the import
string:

```text
uv run uvicorn myapp:application --host 0.0.0.0 --port 8000 --lifespan on
```

Use the exported wrapper attribute, not the async ToriPy factory, and do not add
Uvicorn's `--factory` option. The wrapper is already the ASGI callable that owns
the async application factory.

Direct hosting is the path for Uvicorn options. For example, development reload
can import a fresh wrapper generation:

```text
uv run uvicorn myapp:application --host 127.0.0.1 --port 8000 --lifespan on --reload
```

For multiple worker processes:

```text
uv run uvicorn myapp:application --host 0.0.0.0 --port 8000 --lifespan on --workers 4
```

Each worker owns an independent module graph, singleton set, connection pools,
in-memory data, startup, and shutdown. Size shared downstream resources for the
total across all replicas and workers. Never rely on a ToriPy singleton for
cross-worker coordination.

Uvicorn's options and defaults belong to Uvicorn, not ToriPy's compatibility
contract. Pin and test the selected server version through the application lock
file.

## Lifespan Requirements

Keep `--lifespan on` explicit in production:

- before startup, HTTP receives 503 because no started adapter is available;
- successful startup creates eager singletons, runs hooks, binds routes, and only then admits HTTP;
- startup failure rolls back acquired resources and reports `lifespan.startup.failed`;
- shutdown removes HTTP delegation before running bounded application shutdown;
- a stopped wrapper cannot be restarted; a new import/process must create a new wrapper.

With lifespan disabled, the factory is never awaited and the ToriPy application
never starts. Health checks cannot compensate for a server that does not drive
lifespan.

## `--set` And Direct Hosting

Direct Uvicorn does not parse ToriPy `--set` arguments. Use typed settings from
the process environment, explicit configuration files, dotenv files, or an
application-owned factory configuration. Do not put secrets into command-line
arguments.

## Troubleshooting

| Symptom | Cause | Action |
| --- | --- | --- |
| Missing CLI-extra message | Uvicorn is not installed through the extra | Run `uv add 'tori-py-framework[cli]'`. |
| Factory rejected as synchronous | Target is not an `async def` recognized as a coroutine function | Export a direct async factory without a decorator that hides its coroutine identity. |
| Startup reports `StarletteAdapter` | Factory created a driver-neutral application without the HTTP adapter | Return a fresh application configured with `StarletteAdapter()`. |
| Every request returns 503 | ASGI lifespan has not completed or is disabled | Enable lifespan and inspect startup failure logs. |
| `--set` has no effect under direct Uvicorn | Direct hosting has no CLI bootstrap context | Use environment/files or configure the factory explicitly. |
| Adapter reuse error | One adapter object was shared between applications | Construct a new adapter inside each factory call. |
| Reload or worker state appears empty | Each process/generation has independent memory | Move shared state to an external system with explicit lifecycle providers. |
