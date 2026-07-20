# Project Structure

Keep controllers, services, and module composition in separate files. Nestpy
does not scan packages: the root module explicitly lists provider declarations
and controllers.

From this repository root, sync the workspace with the CLI extra:

```text
uv sync --all-packages --all-groups --extra cli
```

```text
uv run nestpy run examples.nestpy.getting_started.project_structure.app:create_application
```

Request `GET /project/message` to receive
`{"message":"Keep module composition explicit."}`.
