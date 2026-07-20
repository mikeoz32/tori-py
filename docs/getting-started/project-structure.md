# Project Structure

Keep controllers, providers, and module composition in separate files. Nestpy
does not scan packages: the root module lists every controller and provider
declaration explicitly.

The complete runnable layout is at
`examples/nestpy/getting_started/project_structure/`.

```text
uv run nestpy run examples.nestpy.getting_started.project_structure.app:create_application
```

`GET /project/message` returns:

```json
{"message":"Keep module composition explicit."}
```
