# Responses and Errors

ToriPy supports ordinary JSON results, portable pre-encoded `HttpResponse`
values, and native Starlette responses. The selected response form determines
who owns status, headers, encoding, and portability.

## Ordinary JSON Results

Primitives, mappings, sequences, dataclasses, and msgspec structs are encoded
with msgspec JSON. The route owns the status and static response headers:

```python
from tori_py import get, header, status


@get("/profile")
@status(200)
@header("Cache-Control", "private, no-store")
async def profile(self) -> dict[str, str]:
    return {"status": "visible"}
```

The default status is 200 and the content type is `application/json`. A return
annotation does not validate or convert the value. If encoding fails before
response transmission, the failure can be handled by route, controller, or
global filters; otherwise it becomes generic 500 Problem Details.

`@header(name, value)` is stackable on a route method. Header names are
case-insensitively unique and values are static strings. The same HTTP token,
control-character, media-type, and transport-owned framing restrictions apply
at decoration time. Use `HttpResponse` for dynamic headers. Static route headers
apply only to ordinary encoded values.

## Portable Explicit Responses

`HttpResponse` carries final pre-encoded bytes, a status, and headers without a
Starlette dependency:

```python
from secrets import token_hex

from tori_py import HttpResponse, get


@get("/export")
async def export(self) -> HttpResponse:
    return HttpResponse(
        b"ready\n",
        status_code=202,
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "X-Export-ID": token_hex(8),
        },
    )
```

`HttpResponse` enforces:

- `content` is immutable `bytes`;
- status is a non-boolean integer from 200 through 599;
- status 204 or 304 has empty content;
- headers are a mapping copied into an immutable view;
- names are valid HTTP tokens and case-insensitively unique;
- values are strings, Latin-1 encodable, have no surrounding whitespace,
  carriage return, line feed, or prohibited control characters;
- `Content-Type`, when supplied, is one valid media type;
- `Content-Length` and `Transfer-Encoding` are rejected because framing belongs
  to the transport.

Set `Content-Type` explicitly for pre-encoded content. `HttpResponse` does not
infer it from the bytes. Its mapping model permits only one value for each
case-insensitive header name. Use a native Starlette response when the protocol
requires repeated response fields, such as multiple `Set-Cookie` fields.

## Native Starlette Responses

A route may return `starlette.responses.Response` or a subclass for files,
response streaming, or Starlette background tasks:

```python
from starlette.responses import StreamingResponse
from tori_py import get


@get("/events")
async def events(self) -> StreamingResponse:
    async def content():
        yield b"event: ready\n\n"

    return StreamingResponse(content(), media_type="text/event-stream")
```

This is an intentional driver escape hatch. It is not portable to another HTTP
adapter. The request scope remains open until the complete response ASGI call
finishes, including streaming, file transfer, and background tasks. Do not
assume that request-scoped work may continue after the response object returns
from ASGI transmission.

## Response Ownership

| Result | Status owner | Header owner | Content owner |
| --- | --- | --- | --- |
| Ordinary value | `@status` or default 200 | `@header` plus framework request ID | ToriPy msgspec JSON encoding |
| `HttpResponse` | `HttpResponse.status_code` | `HttpResponse.headers` plus framework request ID | Caller-provided bytes |
| Starlette `Response` | Native response | Native response plus framework request ID | Native response |

Route status and static header metadata do not modify either explicit response
kind. In every row, ToriPy removes or overwrites a supplied `X-Request-ID` with
the framework-owned request ID.

## Request IDs

The Starlette adapter accepts exactly one inbound `X-Request-ID` matching
`[A-Za-z0-9._-]{1,128}`. Missing, duplicate, non-ASCII, or invalid values are
replaced with a generated UUIDv7 on the supported Python 3.14 runtime. Invalid
raw values are neither echoed nor included in the warning log.

The final ID is available in context, logging fields, ordinary responses,
explicit responses, redirects, and Problem Details response headers. Treat it
only as correlation metadata; it is not an authentication credential or a
globally unique business identifier.

## Expected HTTP Failures

Raise `HttpException` for an expected HTTP outcome that should use the default
Problem Details renderer:

```python
from tori_py.http import HttpException


async def require_record(record: object | None) -> object:
    if record is None:
        raise HttpException(
            404,
            "Record was not found.",
            title="Record Not Found",
            headers={"Cache-Control": "no-store"},
        )
    return record
```

Constructor fields are:

- `status_code`: response status;
- `detail`: safe client-facing explanation;
- `title`: optional problem title;
- `headers`: optional response headers such as `Retry-After` or `Allow`;
- `errors`: optional structured extension, commonly for validation details.

Use only valid final HTTP statuses and valid response headers. The renderer
always owns `Content-Type` and `X-Request-ID`, so values supplied under those
names are ignored.

## Problem Details

The default response has `application/problem+json` and this shape:

```json
{
  "type": "about:blank",
  "title": "Bad Request",
  "status": 400,
  "detail": "Validation failed.",
  "instance": "/members",
  "errors": {
    "parameter": "member",
    "source": "body",
    "message": "Expected object"
  }
}
```

`errors` appears only when supplied. For normal accepted requests, `instance`
is the request URL path. It is not the request ID; correlation remains in the
`X-Request-ID` header.

Built-in titles cover 400, 403, 404, 405, 413, 415, 500, and 503. Another
status uses `HTTP Error` unless the exception supplies a title.

Default mappings include:

| Condition | Status |
| --- | --- |
| Missing/malformed input or validation failure | 400 |
| Guard returns `False` | 403 |
| No route matches | 404 |
| Path matches but method does not | 405, preserving Starlette's `Allow` header |
| Body exceeds its applicable limit | 413 |
| Parsed body does not use a JSON media type | 415 |
| Unexpected `Exception` | 500 with generic detail |
| Application is not ready | 503 |

Unexpected exception text, request paths/query values, caller request IDs,
representations, and tracebacks are excluded from framework fallback logs.
Those logs contain a fixed event code and a new framework event ID. Application
logging of domain failures remains the application's responsibility and should
follow its own redaction policy.

## Filters and Routing Errors

After a route matches, errors from middleware, guards, binding, pipes,
interceptors, the handler, result validation, and pre-start encoding are offered
to filters in route, controller, then global order. The default renderer runs
last.

404 and 405 occur without a matched route. They are offered only to global
filters with a partial context whose `route_id` is `None`. See
[Interceptors and Filters](../pipeline/interceptors-and-filters.md).

## Response-Start Safety

Before `http.response.start`, a filter or default renderer can replace a failed
result. After response start, status and headers are irrevocable. ToriPy does
not attempt a second response. It records a sanitized transmission failure and
lets the ASGI failure propagate according to server behavior.

Errors while constructing or encoding a response are therefore materially
different from errors raised by a streaming iterator, file sender, or
background task after response transmission starts. Test both boundaries when
using native responses.

## Testing Advice

- Assert status, exact content type, body, static headers, and request ID.
- Test that `@status`/`@header` are ignored by explicit responses.
- Test 204/304 responses with empty bytes.
- Use `raise_app_exceptions=False` for normal HTTP error-contract assertions.
- Use direct ASGI messages for a response implementation that deliberately
  fails after `http.response.start`.
- Never assert that unexpected exception text appears in a 500 response.

## Related API

`status`, `header`, `ResponseHeaderMetadata`, `HttpResponse`, `HttpException`,
`PipelineResult`, and Starlette `Response` subclasses.

Next: [HTTP Context and Injection](context-and-injection.md).
