# Async Factory

`NestApplication.create()` compiles an application but does not open resources,
run hooks, or accept requests. The ASGI lifespan owner starts it later.

Export an async factory, not a started application instance.

From this repository root, sync the workspace with the CLI extra:

```text
uv sync --all-packages --all-groups --extra cli
```

```text
uv run nestpy run examples.nestpy.getting_started.async_factory.app:create_application
```

Request `GET /status` to receive
`{"status":"ready after lifespan startup"}`.
