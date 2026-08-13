# First Controller

Use `@controller()` to declare a controller and an HTTP method decorator to
declare a route. Handler return values are serialized by the Starlette driver.

```python
--8<-- "examples/tori_py/getting_started/hello_world/app.py"
```

The route is attached only because `AppModule` lists `HelloController` in its
`controllers` declaration. Request `GET /hello` to receive
`{"message":"Hello, ToriPy!"}`.

Route decorators record metadata; Starlette remains responsible for route
matching. Typed conversion is not automatic raw binding. Add a pipe when a
handler needs conversion or validation.

## Response Headers

Use `@header()` for static headers on a normal ToriPy-encoded response. Return
`HttpResponse` when the header value or pre-encoded content is dynamic.

```python
from secrets import token_hex

from tori_py import HttpResponse, get, header


@get("/profile")
@header("Cache-Control", "no-store")
@header("X-Content-Type-Options", "nosniff")
async def profile(self) -> dict[str, str]:
    return {"status": "visible"}


@get("/export")
async def export(self) -> HttpResponse:
    return HttpResponse(
        b"ready\n",
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "X-Export-ID": token_hex(8),
        },
    )
```

Static header metadata applies only to ordinary encoded values. An explicit
`HttpResponse` owns its headers, and ToriPy always overwrites `X-Request-ID` with
the framework request ID.
