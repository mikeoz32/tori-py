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

## Routes Without Bodies

Use `@no_body` when a route contract requires an empty request stream:

```python
from tori_py import HttpResponse, no_body, post


@post("/members/refresh")
@no_body
async def refresh(self) -> HttpResponse:
    return HttpResponse(b"", status_code=204)
```

The check is opt-in and uses the actual stream, not `Content-Length`. Guards run
first. A supplied body is rejected before pipes, interceptors, or the handler,
and `@no_body` cannot be combined with a `Body()` binding. Tori Py reads through
EOF or cumulative size-limit overflow: non-empty content within the limit is a
400 response, while content above it is a 413 response regardless of ASGI
chunking.

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
