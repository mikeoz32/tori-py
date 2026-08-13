# CLI Run

Install the optional server integration, then use the only supported v1 serving
command:

```text
uv sync --all-packages --all-groups --extra cli
uv run tori-py run examples.tori_py.getting_started.cli_run.app:create_application
```

The CLI passes the factory to the production ASGI lifespan wrapper. It does not
create or start an application in a separate event loop.

Request `GET /greeting` to receive
`{"message":"Serve factories with tori-py run."}`.
