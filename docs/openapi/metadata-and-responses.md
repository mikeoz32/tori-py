# Metadata and Responses

Type annotations provide schemas. Decorators provide the API meaning that cannot
be inferred safely from runtime code.

## Decorator Reference

| Decorator | Controller | Route | Purpose |
| --- | --- | --- | --- |
| `api_tags(*tags)` | Yes | Yes | Group operations |
| `api_operation(...)` | No | Yes | Summary, description, ID, deprecation |
| `api_parameter(...)` | No | Yes | Refine a bound parameter schema |
| `api_response(status, ...)` | Yes | Yes | Explicit response |
| `api_security(name, scopes=())` | Yes | Yes | Bearer security alternative; keep `scopes=()` in this release |
| `api_public()` | No | Yes | Clear inherited security |
| `api_exclude()` | Yes | Yes | Omit from document |

Decorators attach immutable metadata directly to the target. They do not
register controllers, install guards, or inspect handler bodies.

## Tags and Operations

```python
from tori_py_openapi import api_operation, api_tags


@api_tags("members")
class MembersController:
    @api_tags("profiles")
    @api_operation(
        summary="Read a profile",
        operation_id="profiles_read",
        deprecated=False,
    )
    async def read(self) -> Profile:
        """Return profile fields visible to the caller."""
        ...
```

Controller tags come first, route tags follow, and duplicates are removed while
preserving order. Operation IDs must be globally unique. Without an explicit ID,
the compiler derives one from the controller qualified name and method name.

## Docstring Descriptions

When `api_operation(description=...)` is absent, the cleaned method docstring
becomes the operation description:

```python
@api_operation(summary="Read a profile")
async def read(self) -> Profile:
    """Return fields visible under the current privacy policy.

    This paragraph is public too.

    \f
    Internal query and authorization notes are not published.
    """
```

Text after the first `\f` is excluded. Explicit descriptions always win.
Summaries are never inferred from docstrings.

## Explicit Responses

Add known alternative outcomes explicitly:

```python
import msgspec
from tori_py_openapi import api_response


class Problem(msgspec.Struct):
    detail: str


@api_response(404, description="Profile not found", model=Problem)
@api_response(403, description="Profile is not visible", model=Problem)
async def read(self) -> Profile:
    ...
```

An explicit response matching the route's primary status completely replaces
inference for that status. It does not inherit the return schema, inferred media
type, or static response headers.

Controller response metadata acts as a default. A route declaration with the
same status replaces it; route-only statuses are appended.

Omit `model=` for a bodyless documented response. Explicit models default to
`application/json`; set `media_type=` for another representation. Use
`headers={"Name": "example"}` to document static response headers:

```python
@api_response(
    422,
    model=Problem,
    media_type="application/problem+json; charset=utf-8",
    headers={"Retry-After": "30"},
)
async def update(self) -> Profile:
    ...
```

Media-type parameters are omitted from the OpenAPI content key. `Content-Type`
must be expressed through `media_type`; `X-Request-ID` is framework-owned and
cannot be declared. Models are prohibited for 204 and 304, but those responses
may declare headers and still omit `content`.

## Static Response Headers

Use ToriPy's `@header()` for static headers on ordinary encoded responses:

```python
from tori_py import get, header


@get("/profile")
@header("Cache-Control", "private, no-store")
@header("X-Content-Type-Options", "nosniff")
async def profile(self) -> Profile:
    ...
```

The decorator is stackable. Names are case-insensitively unique and values are
static strings. `Content-Length` and `Transfer-Encoding` are transport-owned.
ToriPy always overwrites `X-Request-ID` with the framework request ID.

For inferred responses, non-framework headers are documented as string headers
with their static value as an example. A valid `Content-Type` header selects the
OpenAPI media type instead of appearing under `headers`.

## Dynamic and Pre-encoded Responses

Use `HttpResponse` when content, status, or headers are dynamic or already
encoded:

```python
from secrets import token_hex

from tori_py import HttpResponse, get
from tori_py_openapi import api_response


@get("/export")
@api_response(200, description="UTF-8 profile export")
async def export(self) -> HttpResponse:
    return HttpResponse(
        b"profile export\n",
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "X-Export-ID": token_hex(8),
        },
    )
```

`HttpResponse` and `PipelineResult` are opaque to schema inference and require at
least one explicit `api_response`. An explicit `HttpResponse` owns its headers;
route `@header` metadata applies only to ordinary ToriPy-encoded values.

!!! warning "Opaque means the body is not described"
    Declare `model=`, `media_type=`, and static header examples when the opaque
    response has a stable contract. Dynamic header values remain examples rather
    than runtime validation.

For 204 and 304, use empty `HttpResponse` content and a model-free declaration:

```python
from typing import Annotated

from tori_py import HttpResponse, Path, delete, status
from tori_py_openapi import api_response


@delete("/{member_id}")
@status(204)
@api_response(204, description="Member deleted")
async def delete_member(
    self,
    member_id: Annotated[str, Path("member_id")],
) -> HttpResponse:
    return HttpResponse(b"", status_code=204)
```

## Excluding Routes

Use `api_exclude()` for operational or native escape-hatch routes that should
not be public documentation:

```python
from tori_py_openapi import api_exclude


@api_exclude()
async def internal_probe(self) -> dict[str, str]:
    return {"status": "internal"}
```

Exclusion does not remove runtime routing. Earlier excluded templates can still
shadow later documented routes, so the compiler retains them for selected
ordering diagnostics.
