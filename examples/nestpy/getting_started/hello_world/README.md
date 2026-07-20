# Hello World

The smallest Nestpy application has a controller, a root module, an async
factory, and an ASGI wrapper.

From this repository root, sync the workspace with the CLI extra:

```text
uv sync --all-packages --all-groups --extra cli
```

```text
uv run nestpy run examples.nestpy.getting_started.hello_world.app:create_application
```

Request `GET /hello` to receive `{"message":"Hello, Nestpy!"}`.
