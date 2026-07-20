# First Provider

A `ClassProvider` creates a provider declaration for a class. A controller
constructor requests that class as its provider token.

```python
--8<-- "examples/nestpy/getting_started/first_provider/app.py"
```

Run it from this repository root:

```text
uv run nestpy run examples.nestpy.getting_started.first_provider.app:create_application
```

`GET /greeting` returns:

```json
{"message":"Providers are explicit constructor dependencies."}
```

The module owns the provider declaration. Later modules must import an exported
provider token to use it; module visibility is not implicit.
