# First Application

An application factory compiles a root module. The ASGI server owns startup and
shutdown through the wrapper, so the factory must return an unstarted
application.

```python
--8<-- "examples/nestpy/getting_started/hello_world/app.py"
```

From this repository root, serve the example:

```text
uv run nestpy run examples.nestpy.getting_started.hello_world.app:create_application
```

Request `GET /hello`. The response is:

```json
{"message":"Hello, Nestpy!"}
```

For a manually exported ASGI callable, inspect the runnable source at
`examples/nestpy/getting_started/asgi_wrapper/app.py`.
