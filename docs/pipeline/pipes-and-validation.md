# Pipes and Validation

Pipes are the only built-in request argument conversion point. Binding extracts
raw transport values first; each configured pipe then transforms one argument
at a time before interceptors and the handler run.

## Opt-In Msgspec Validation

`MsgspecValidationPipe` converts a raw value to the route parameter's declared
annotation:

```python
from typing import Annotated

import msgspec
from tori_py import Body, Query, controller, post, use_pipe
from tori_py.http import MsgspecValidationPipe


class CreateMember(msgspec.Struct, forbid_unknown_fields=True):
    handle: str
    display_name: str


@controller("/members")
@use_pipe(MsgspecValidationPipe())
class MembersController:
    @post("")
    async def create(
        self,
        body: Annotated[CreateMember, Body()],
        notify: Annotated[bool, Query("notify")] = False,
    ) -> dict[str, object]:
        return {
            "handle": body.handle,
            "notify": notify,
        }
```

Without the pipe, `body` is a raw dictionary and a supplied `notify=true` is the
string `"true"`. The annotation alone changes neither value.

Register the pipe globally when all ordinary HTTP routes share the policy:

```python
from tori_py import PipelineOptions
from tori_py.http import MsgspecValidationPipe

pipeline = PipelineOptions(pipes=(MsgspecValidationPipe(),))
```

The preconstructed pipe is externally owned and shared. This implementation is
stateless. For a lifecycle-managed custom pipe, register a provider token or
implementation class instead.

## Execution Order

ToriPy binds all parameters before running any pipe. It then visits parameters
in handler signature order. For each eligible parameter it runs:

1. All global pipes in registration order.
2. All controller pipes in registration order.
3. All route pipes in registration order.

The output of one pipe is the input to the next. Only after every eligible
argument is transformed do interceptors and the handler run.

`Context()` and `Inject()` arguments never pass through pipes. All other current
binding kinds do, including path, query, header, cookie, parsed body, and raw
body stream. Python defaults selected for missing HTTP values also pass through
pipes.

Do not attach `MsgspecValidationPipe` to a `BodyStream()` route without a
pass-through policy for `metadata.binding_kind == "body_stream"`; converting the
stream protocol is not meaningful.

## Argument Metadata

Every pipe receives immutable `ArgumentMetadata`:

| Field | Value |
| --- | --- |
| `parameter_name` | Python handler parameter name |
| `binding_kind` | `path`, `query`, `header`, `cookie`, `body`, or `body_stream` |
| `source_name` | Explicit marker source name, or `None` for body bindings |
| `annotation` | Resolved base annotation from `Annotated` |
| `route_id` | Compiled `"METHOD /path"` identifier |
| `module_id` | Owning module label |

A custom pipe should use this metadata rather than guessing from parameter names:

```python
from tori_py import ArgumentMetadata


class TrimQueryStrings:
    async def transform(
        self,
        value: object,
        metadata: ArgumentMetadata,
    ) -> object:
        if metadata.binding_kind != "query":
            return value
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return [item.strip() for item in value]
        return value
```

Raise `HttpException` for a safe, expected client error. Other `Exception`
values proceed through filters and normally become generic 500 responses.

## Msgspec Conversion Behavior

`MsgspecValidationPipe` first asks `msgspec.convert` for the declared target. It
also handles common raw HTTP shapes:

- string integers and floats convert to `int` and `float`;
- case-insensitive `true`/`1` and `false`/`0` convert to `bool`;
- repeated raw lists convert item-by-item for list, tuple, set, and frozenset
  annotations;
- union targets first receive one direct `msgspec.convert` attempt; only after
  that fails are non-`None` branches tried in declaration order;
- parsed JSON dictionaries/lists convert to msgspec-compatible structs,
  dataclasses, collections, and scalar targets.

The target annotation must be supported by msgspec. Direct union conversion may
succeed without using the branch fallback. Avoid broad or ambiguous unions for
untrusted text because declaration order controls the fallback after direct
conversion fails and can therefore become part of the API contract.

On `TypeError`, `ValueError`, or `msgspec.ValidationError`, the pipe raises:

```text
HttpException(400, "Validation failed.")
```

The resulting Problem Details includes:

```json
{
  "errors": {
    "parameter": "body",
    "source": "body",
    "message": "<safe msgspec conversion message>"
  }
}
```

The exact msgspec message can change with the pinned msgspec version. Assert
stable fields and status in API tests unless the message itself is part of the
application's contract.

## Raw and Converted Shapes

| Declaration | Without validation pipe | With validation pipe |
| --- | --- | --- |
| `Annotated[int, Path("id")]` | `str` | `int` |
| `Annotated[bool, Query("active")]` | `str` | `bool` |
| `Annotated[list[int], Query("id")]` with repeated values | `list[str]` | `list[int]` |
| `Annotated[CreateMember, Body()]` | `dict[str, object]` | `CreateMember` |
| Missing query with default `10` | `10` | Converted/validated against annotation |

A single repeated-capable query/header source binds one string, not a list.
When the annotation requires a collection, the current msgspec pipe's first
conversion attempt must be able to interpret that single value; design and test
the API explicitly rather than assuming automatic one-item list wrapping.

## Pipe Composition

Registration order is semantic. For example, trimming before validation differs
from validating before trimming. Keep one conversion owner:

```text
raw extraction -> normalization pipe -> validation/conversion pipe -> handler
```

Do not register `MsgspecValidationPipe` at both global and route levels. The
second pipe receives an already converted value and can hide an accidental
double-decoding design.

Pipes run after all argument binding. A missing later argument prevents any
pipe from running, even if earlier values were successfully extracted. Do not
put body-read side effects in a pipe under the assumption that it executes
during extraction.

## Failure and Filter Behavior

A pipe failure occurs after guards and binding but before interceptors and the
handler. Route, controller, and global filters may map the exception. A
validation `HttpException` that no filter replaces is rendered as 400 Problem
Details with the structured `errors` extension.

Cancellation and client-disconnect aborts bypass filters and must not be
converted into validation responses.

## Testing

The tested Task API registers `MsgspecValidationPipe` and exercises body and
path conversion:

```python
--8<-- "packages/tori-py/tests/docs/test_task_api_reference.py"
```

Add focused tests for:

- raw values when no pipe is registered;
- valid and invalid scalar conversion;
- repeated values and the single-value case;
- nested body models, missing fields, wrong types, and unknown fields;
- pipe order for every parameter in signature order;
- exclusion of `Context()` and `Inject()`;
- body-stream pass-through when global pipes are present.

## Production Considerations

- Use strict, bounded input models and avoid accepting arbitrary nested objects.
- Keep normalization deterministic and side-effect free.
- Do not include secrets or complete request bodies in validation messages or
  logs.
- Validate domain invariants in application/domain services even after shape
  validation.
- Pin and test msgspec behavior that becomes part of a public API.

## Related API

`Pipe`, `ArgumentMetadata`, `MsgspecValidationPipe`, `PipelineOptions`,
`use_pipe`, `use_pipes`, `pipes`, `Body`, `Path`, `Query`, `Header`, and `Cookie`.

Next: [Interceptors and Filters](interceptors-and-filters.md).
