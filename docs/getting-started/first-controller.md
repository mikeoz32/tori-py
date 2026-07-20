# First Controller

Use `@controller()` to declare a controller and an HTTP method decorator to
declare a route. Handler return values are serialized by the Starlette driver.

```python
--8<-- "examples/nestpy/getting_started/hello_world/app.py"
```

The route is attached only because `AppModule` lists `HelloController` in its
`controllers` declaration. Request `GET /hello` to receive
`{"message":"Hello, Nestpy!"}`.

Route decorators record metadata; Starlette remains responsible for route
matching. Typed conversion is not automatic raw binding. Add a pipe when a
handler needs conversion or validation.
