# Configuration

`SettingsModule.for_root()` loads a typed settings model during application
compilation. The model class becomes a provider token and can be requested from
a controller constructor.

```python
--8<-- "examples/nestpy/getting_started/first_settings/app.py"
```

```text
uv run nestpy run examples.nestpy.getting_started.first_settings.app:create_application
```

`GET /greeting` returns `{"message":"Hello from settings"}`. This small
example intentionally supplies an empty environment mapping so its output is
self-contained. Production settings can use the process environment, files,
and CLI overrides; those sources are covered in the Settings guide.
