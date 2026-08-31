# Controllers and Routes

Controllers group route declarations and receive constructor-injected singleton
dependencies. They become active only when explicitly listed in a module's
`controllers` declaration.

## Declaring Routes

This focused controller fragment uses only public declarations:

```python
from typing import Annotated

from tori_py import Path, controller, get, post, status


@controller("/users")
class UsersController:
    @get("/me")
    async def current(self) -> dict[str, str]:
        return {"user": "current"}

    @get("/{user_id}")
    async def get_one(
        self,
        user_id: Annotated[str, Path("user_id")],
    ) -> dict[str, str]:
        # The default Starlette path converter supplies a string.
        return {"user_id": user_id}

    @post("")
    @status(201)
    async def create(self) -> dict[str, str]:
        return {"status": "created"}
```

Register the controller explicitly:

```python
from tori_py import module


@module(controllers=[UsersController])
class UsersModule:
    pass
```

Controllers are eager singleton providers. ToriPy constructs and binds each
controller once during startup, not once per request. A controller therefore
must not store request-specific state on `self`; use request-scoped providers or
handler arguments instead.

## Route Decorators

The public convenience decorators are `get`, `post`, `put`, `patch`, `delete`,
`head`, and `options`. Use `route(method, path)` for another HTTP method.
Methods are normalized to uppercase.

Both synchronous and asynchronous handlers are accepted. Handler parameters
must follow the explicit binding rules in [Request Binding](binding.md).
Variadic `*args` and `**kwargs` are rejected during compilation. Use normal
named or keyword-only parameters; positional-only parameters cannot be invoked
through ToriPy's keyword argument dispatch.

Route declarations are read directly from the controller class body. Define
routed methods on the registered controller itself rather than relying on
inherited route methods or inherited controller metadata.

## Path Joining

ToriPy joins the controller prefix and route path at their boundary:

| Prefix | Route path | Compiled path |
| --- | --- | --- |
| `""` | `""` | `/` |
| `"users"` | `""` | `/users` |
| `"/users"` | `"/{id}"` | `/users/{id}` |
| `"/users/"` | `"/{id}"` | `/users/{id}` |
| `"/users"` | `"{id}"` | `/users/{id}` |

Joining adds one leading slash and removes only a duplicate slash at the
prefix/path boundary. It does not otherwise canonicalize the path. Trailing
slashes, segment spelling, parameter names, converter text, and additional
slashes remain significant.

## Duplicate Routes

Compilation rejects an exact duplicate normalized `(method, path)` across the
entire module graph. A `GET` route also reserves `HEAD` for the same path, so an
explicit `HEAD` route and `GET` route for that exact path conflict regardless of
declaration order.

The duplicate check is deliberately narrow:

- `/items` and `/items/` are different declarations.
- `/{id}` and `/{name}` are different declarations.
- `/{id}` and `/{id:int}` are different declarations.
- Different methods on the same path are different, except for the
  `GET`/implicit-`HEAD` rule.

These non-identical declarations can still overlap at runtime. ToriPy does not
try to prove whether two Starlette patterns match the same request.

## Route Ordering

Starlette routes are built in deterministic declaration order:

1. Compiled module order.
2. Controller order in each module's `controllers` tuple.
3. Method definition order in each controller class body.

Starlette uses the first matching route. Put specific literal routes before
parameter routes and catch-all converters:

```python
@controller("/files")
class FilesController:
    @get("/latest")
    async def latest(self) -> str:
        return "latest"

    @get("/{path:path}")
    async def by_path(
        self,
        path: Annotated[str, Path("path")],
    ) -> str:
        return path
```

Reversing those methods allows the catch-all route to claim `/files/latest`.
Apply the same rule across controllers and modules when their prefixes overlap.

Trailing-slash redirects, path converter semantics, implicit `HEAD`, automatic
or explicit `OPTIONS`, and 405 `Allow` headers belong to the pinned Starlette
version. Test the externally visible behavior instead of assuming another
framework's router rules.

## Status Metadata

`@status(code)` supplies the status for an ordinary ToriPy-encoded result. The
default is 200. Status metadata accepts HTTP codes from 100 through 599, but it
does not validate the handler's payload against that status.

`HttpResponse` and native Starlette responses ignore route status metadata and
own their status. For bodyless final statuses such as 204, return an explicit
empty `HttpResponse`:

```python
from tori_py import HttpResponse, post


@post("/refresh")
async def refresh(self) -> HttpResponse:
    return HttpResponse(b"", status_code=204)
```

Returning `None` from an ordinary 200 route encodes JSON `null`; it does not
imply 204.

## Compilation Semantics

ToriPy inspects route signatures and resolves annotations while compiling the
application. The immutable route plan stores the handler parameter annotations,
return annotation, status, headers, body policy, and pipeline metadata. It does
not inspect annotations again for each request.

Return annotations are descriptive only. They do not validate, convert, or
change the runtime response. An omitted return annotation remains distinct in
compiled metadata from an explicit `-> None`, but both follow the same response
encoding rules.

The public `compile_controller_routes(module_id, controller)` helper exposes the
same transport-neutral compilation for integrations. Normal applications should
declare controllers in modules and let `NestApplication` compile the graph.

## Failure Behavior

Invalid controller metadata, duplicate routes, unresolved annotations,
variadics, contradictory body declarations, and invalid parameter markers fail
before startup with `BootstrapError`. Runtime path matching failures become 404
or 405 Problem Details and can be handled only by global filters because no
controller route matched.

## Testing and Production Advice

- Test every intentional overlap and trailing-slash policy through the
  Starlette adapter.
- Keep one canonical spelling for route paths even though the compiler preserves
  distinct spellings.
- Avoid broad catch-all routes near the beginning of the route table.
- Treat converter behavior as Starlette-specific.
- Keep controllers stateless with respect to individual requests.
- Assert startup failure for duplicate routes in module-level tests.

## Related API

`controller`, `route`, `get`, `post`, `put`, `patch`, `delete`, `head`,
`options`, `status`, `module`, `BootstrapError`, `compile_controller_routes`,
`RoutePlan`, and `ParameterPlan`.

Next: [Request Binding](binding.md).
