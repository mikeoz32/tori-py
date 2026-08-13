# ASGI Wrapper

ASGI servers import synchronous callables. Wrap an async factory with `asgi()`:

```python
application = asgi(create_application)
```

The wrapper creates and starts the ToriPy application once during ASGI lifespan.

From this repository root, sync the workspace with the CLI extra:

```text
uv sync --all-packages --all-groups --extra cli
```

```text
uv run tori-py run examples.tori_py.getting_started.asgi_wrapper.app:create_application
```

Request `GET /health` to receive `{"status":"ok"}`.
