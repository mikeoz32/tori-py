# Schemas and Routes

OpenAPI generation starts from Nestpy's compiled `RoutePlan` values. The same
controller paths, binding sources, defaults, status metadata, and resolved type
annotations used by runtime routing are the input to documentation generation.

!!! warning "Schemas do not enable runtime validation"
    Nestpy bindings initially provide raw path, query, header, cookie, and
    decoded JSON values. `nestpy-openapi` documents annotations but does not
    convert or validate requests. Register `MsgspecValidationPipe` when handlers
    need typed values matching the generated schemas.

## Parameters

```python
from typing import Annotated, Literal

from nestpy import Header, Path, Query, controller, get


@controller("/members")
class MembersController:
    @get("/{handle}")
    async def read(
        self,
        handle: Annotated[str, Path("handle")],
        detail: Annotated[Literal["summary", "full"], Query("detail")] = "summary",
        locale: Annotated[str, Header("Accept-Language")] = "en",
    ) -> dict[str, str]:
        return {"handle": handle, "detail": detail, "locale": locale}
```

`Path`, `Query`, `Header`, and `Cookie` become OpenAPI parameters. `Context` and
`Inject` are runtime concerns and are omitted.

Presence and nullability are separate:

```python
query: Annotated[str | None, Query("q")]          # required, nullable
optional: Annotated[str | None, Query("q")] = None  # optional, nullable
```

Path bindings must exactly match route variables and are always required.
Duplicate `(source name, location)` pairs fail startup.

!!! note
    `Header("X-Value")` is a request binding marker. Lowercase
    `@header("X-Value", "static")` declares a response header.

## JSON Request Bodies

Nestpy currently supports one JSON body binding per route:

```python
from typing import Annotated

import msgspec
from nestpy import Body, post, use_pipe
from nestpy.http import MsgspecValidationPipe


class CreateMember(msgspec.Struct):
    handle: str
    display_name: str


@post("/members")
@use_pipe(MsgspecValidationPipe())
async def create(
    self,
    body: Annotated[CreateMember, Body()],
) -> CreateMember:
    return body
```

The document uses `application/json` and marks the request body required,
matching current Nestpy body-presence behavior. A Python body default does not
make the OpenAPI body optional and is not copied into its schema.

Without the validation pipe, `body` would be the raw decoded dictionary despite
its `CreateMember` annotation. The same distinction applies to numeric path
values and structured query values.

Multipart, forms, files, multiple bodies, and per-body media types are not in
this release.

## Response Inference

For ordinary handler values, the primary response comes from the route status
and return annotation:

```python
import msgspec
from nestpy import post, status


class MemberView(msgspec.Struct):
    handle: str


@post("/members")
@status(201)
async def create(self) -> MemberView:
    return MemberView(handle="example")
```

This produces a `201 Created` response with a schema reference to `MemberView`.
If no return annotation exists, the response contains only its description.

## Model Types

The compiler supports msgspec's schema model with stricter fail-fast checks:

- `msgspec.Struct`;
- dataclasses;
- `TypedDict`;
- named tuples;
- scalar and container annotations supported by msgspec;
- enums and `Literal` values;
- Python 3.14 `type Alias = ...` aliases.

Components are shared under `#/components/schemas/{name}` and generated in one
msgspec pass.

```python
from dataclasses import dataclass
from typing import TypedDict

import msgspec


class Coordinates(TypedDict):
    latitude: float
    longitude: float


@dataclass
class Location:
    label: str
    coordinates: Coordinates


class Profile(msgspec.Struct):
    handle: str
    location: Location | None
```

## Unions

The supported union subset is intentionally deterministic:

| Shape | Example | Supported |
| --- | --- | --- |
| Scalar union | `int | str | None` | Yes |
| Nullable model | `Profile | None` | Yes |
| Tagged structs | `PhotoPost | TextPost` | Yes |
| Untagged models | `Cat | Dog` | No |
| Mixed scalar/model | `int | Profile` | No |
| Mixed container/model | `list[int] | Profile` | No |

Tagged msgspec structs produce a discriminator:

```python
import msgspec


class TextPost(msgspec.Struct, tag="text"):
    text: str


class PhotoPost(msgspec.Struct, tag="photo"):
    image_url: str


async def post(self) -> TextPost | PhotoPost:
    ...
```

`Any`, unconstrained `object`, unresolved references or type variables,
unsupported unions, empty schemas, and component-name collisions fail rather
than degrading to an unconstrained schema. Nestpy can reject directly unresolved
handler annotations during `NestApplication.create()`; references discovered
inside schema models fail during OpenAPI startup generation.

## Parameter Defaults

Only strict native JSON values are documented as defaults: `None`, booleans,
integers, finite floats, strings, lists, and string-keyed dictionaries composed
of the same values. Tuples, bytes, non-finite floats, custom objects, and cyclic
structures are rejected.

Defaults are copied, so mutating the original list or dictionary later cannot
change the generated document.
