# First Provider

`ClassProvider(GreetingService)` makes `GreetingService` available to the
controller constructor. Constructor annotations select provider class tokens.

From this repository root, sync the workspace with the CLI extra:

```text
uv sync --all-packages --all-groups --extra cli
```

```text
uv run tori-py run examples.tori_py.getting_started.first_provider.app:create_application
```

Request `GET /greeting` to receive
`{"message":"Providers are explicit constructor dependencies."}`.
