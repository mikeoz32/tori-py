# First Settings

`SettingsModule.for_root()` loads a typed model during application compilation.
The model class is exported as a provider token, so controllers can request it
through constructor injection.

From this repository root, sync the workspace with the CLI extra:

```text
uv sync --all-packages --all-groups --extra cli
```

```text
uv run tori-py run examples.tori_py.getting_started.first_settings.app:create_application
```

Request `GET /greeting` to receive `{"message":"Hello from settings"}`.
