# Project Structure

Keep controllers, providers, and module composition in separate files. ToriPy
does not scan packages: the root module lists every controller and provider
declaration explicitly.

The complete runnable layout is at
`examples/tori_py/getting_started/project_structure/`.

```text
uv run tori-py run examples.tori_py.getting_started.project_structure.app:create_application
```

`GET /project/message` returns:

```json
{"message":"Keep module composition explicit."}
```
