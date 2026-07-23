# First Provider

`@injectable()` marks a class for self-token provider shorthand. Listing that
class in `providers` compiles it into a `ClassProvider`; a controller constructor
requests the class as its provider token. Use an explicit `ClassProvider` when
the token, implementation, scope, or resource ownership belongs in composition.

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
