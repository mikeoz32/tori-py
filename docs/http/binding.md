# Request Binding

Every route parameter other than `self` declares exactly one source. ToriPy
extracts that source as a raw transport value. The declared Python annotation is
metadata for pipes and integrations; it does not perform conversion by itself.

## Binding Markers

Use `typing.Annotated` with one marker:

| Marker | Bound value |
| --- | --- |
| `Body()` | Parsed JSON-compatible Python value |
| `BodyStream(max_bytes=...)` | `HttpBodyStream` of raw byte chunks |
| `Path(name)` | Raw path string |
| `Query(name)` | Raw string, or `list[str]` when repeated |
| `Header(name)` | Raw string, or `list[str]` when repeated |
| `Cookie(name)` | Raw cookie string |
| `Context()` | Portable `HttpContext` or compatible adapter context |
| `Inject(token)` | Provider resolved from the route's module in this request scope |

Source names are always explicit. ToriPy does not infer `Query("page")` from a
parameter named `page`, and an HTTP marker cannot be combined with `Inject`.

## Raw Means Raw

This handler annotates `page` as `int`, but without a pipe it receives a string:

```python
from typing import Annotated

from tori_py import Query, controller, get


@controller("/search")
class SearchController:
    @get("")
    async def search(
        self,
        page: Annotated[int, Query("page")],
        tags: Annotated[list[str], Query("tag")],
    ) -> dict[str, object]:
        return {
            "page": page,
            "page_type": type(page).__name__,
            "tags": tags,
        }
```

`GET /search?page=7&tag=python&tag=asgi` passes `"7"` for `page` and
`["python", "asgi"]` for `tags`. A single `tag` value is a string, not a
one-element list. Register `MsgspecValidationPipe` when the handler requires
stable annotated types.

Raw extraction by source is exact:

- Path values are whatever Starlette placed in `path_params`. The default path
  converter supplies a string; explicit Starlette converters can supply values
  such as `int`, `float`, or UUID. That router conversion is independent of the
  handler annotation and ToriPy pipes.
- Query and header lookup preserves repeated fields as a list and collapses one
  field to one string.
- Header lookup follows Starlette's case-insensitive header behavior.
- Cookie lookup returns one parsed cookie string.
- JSON parsing naturally produces JSON types such as dictionaries, lists,
  strings, integers, floats, booleans, and `None`; it does not construct the
  annotated dataclass or msgspec struct.

## Complete Binding Shape

The following focused route shows the marker forms that can coexist. A route may
have only one body-consuming marker, so `Body()` and `BodyStream()` never appear
together.

```python
from typing import Annotated

from tori_py import Body, Context, Cookie, Header, Inject, Path, Query, post
from tori_py.http import HttpContext


@post("/{item_id}")
async def update(
    self,
    item_id: Annotated[int, Path("item_id")],
    payload: Annotated[dict[str, object], Body()],
    context: Annotated[HttpContext, Context()],
    service: Annotated[object, Inject("items.service")],
    verbose: Annotated[bool, Query("verbose")] = False,
    request_token: Annotated[str, Header("X-Request-Token")] = "",
    session: Annotated[str, Cookie("session")] = "anonymous",
) -> object:
    del context, service
    return {
        "item_id": item_id,
        "payload": payload,
        "verbose": verbose,
        "request_token": request_token,
        "session": session,
    }
```

`Body()` always attempts JSON media-type validation and parsing. Giving a body
parameter a Python default would not turn an absent JSON document into an
omitted body value. Prefer a required body parameter and model optional fields
inside the JSON schema.

## Missing Values and Defaults

For path, query, header, and cookie bindings, a missing value produces 400
Problem Details unless the Python parameter has a default. The default becomes
the bound value and still passes through configured pipes.

An empty string is present, not missing. For example, `?query=` binds `""` and
does not select the default.

`Context()` and `Inject()` are supplied by the framework rather than read from
the request. Provider resolution failures follow the normal DI error path and
can be handled by filters before response start.

## Signature Validation

Route compilation requires:

- exactly one recognized marker on every non-`self` parameter;
- no unrelated extra `Annotated` metadata in the binding annotation;
- a non-empty explicit source name for path, query, header, and cookie markers;
- at most one `Body()` or `BodyStream()` parameter;
- exactly `HttpBodyStream` as the base annotation for `BodyStream()`;
- `HttpContext` or a compatible subtype for `Context()`;
- no variadic parameters.

The Starlette adapter additionally checks that its concrete `RequestContext`
can satisfy a context annotation. Annotate `HttpContext` for portable code or
`RequestContext` when native Starlette access is intentional.

## JSON Body Binding

`Body()` accepts `application/json` and media types with a `+json` suffix,
including parameters such as `charset`. The Starlette adapter reads the actual
ASGI chunks, enforces `StarletteOptions.body_size_limit`, and parses the body
once. Errors map as follows:

| Condition | Status |
| --- | --- |
| Missing or unsupported JSON media type | 415 |
| Malformed JSON, including an empty document | 400 |
| Actual body bytes exceed the configured limit | 413 |

`Content-Length` is not trusted as proof of actual content or size. See
[Request Bodies and Streaming](body-streaming.md) for raw streaming and
`@no_body`.

## Conversion and Validation

Conversion has one extension point: pipes. `MsgspecValidationPipe` converts each
raw HTTP-bound value to its declared annotation and emits structured 400 Problem
Details when conversion fails:

```python
from typing import Annotated

from tori_py import Query, controller, get, use_pipe
from tori_py.http import MsgspecValidationPipe


@use_pipe(MsgspecValidationPipe())
@controller("/search")
class ValidatedSearchController:
    @get("")
    async def search(
        self,
        page: Annotated[int, Query("page")],
    ) -> int:
        return page
```

Controller and route pipeline decorators may be placed in either Python
decorator order as long as each decorator targets the intended class or method.
Do not register the validation pipe twice; every pipe transforms the output of
the preceding pipe.

## Testing Advice

Test both sides of the conversion boundary:

- Without a validation pipe, assert that numeric path/query values remain
  strings and repeated values remain raw lists.
- With a validation pipe, assert the handler receives the annotated scalar,
  collection, dataclass, or msgspec struct.
- Test missing, empty, repeated, malformed, wrong-media-type, and oversized
  inputs separately.
- Do not call handlers directly for binding tests; use the Starlette adapter so
  extraction behavior is exercised.

## Production Advice

- Use narrow input models and enable strict model options such as msgspec
  `forbid_unknown_fields=True` where appropriate.
- Validate authorization independently of conversion.
- Bound body size at the edge and in `StarletteOptions`.
- Do not annotate a type merely for editor convenience if the handler actually
  accepts a raw union of `str | list[str]`; either reflect the raw shape or add a
  conversion pipe.

## Related API

`Body`, `BodyStream`, `Path`, `Query`, `Header`, `Cookie`, `Context`, `Inject`,
`HttpBodyStream`, `HttpContext`, `RequestContext`, `ArgumentMetadata`, and
`MsgspecValidationPipe`.

Next: [Pipes and Validation](../pipeline/pipes-and-validation.md).
