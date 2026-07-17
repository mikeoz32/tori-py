# Nestpy Example

Install the CLI extra and serve the example with:

```text
uv add 'nestpy[cli]'
nestpy run examples.nestpy.app:create_application --set greeting=hello
```

The application uses public Nestpy imports, typed settings, a request-scoped
provider, a guard, the opt-in msgspec validation pipe, a filter, and the
production Starlette lifespan wrapper.
