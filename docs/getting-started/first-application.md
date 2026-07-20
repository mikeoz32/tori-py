# First Application

An application factory compiles a root module. The ASGI server owns startup and
shutdown through the wrapper, so the factory must return an unstarted
application. `NestApplication` is driver-neutral; this HTTP example selects the
explicit `StarletteAdapter`.

DI-managed global Nestpy middleware, guards, pipes, interceptors, and filters
belong to driver-neutral `PipelineOptions`. An application factory can append
preconstructed instances or already-visible provider tokens before returning with
`use_global_guard()`, `use_global_pipe()`, `use_global_interceptor()`, and
`use_global_filter()`. `StarletteOptions` contains only settings for the
Starlette transport. Visible tokens and registered class tokens retain DI scope
and lifecycle ownership; preconstructed instances remain externally owned.
Unregistered enhancer classes must be supplied through `PipelineOptions` so
they can become providers during compilation.

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
`examples/nestpy/getting_started/asgi_wrapper/app.py`. Its factory configures a
global guard and returns the unstarted application; `asgi(create_application)`
still owns startup and shutdown.
