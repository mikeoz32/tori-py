# OpenAPI

`nestpy-openapi` is the optional OpenAPI 3.1 and Swagger UI integration for
Nestpy. It discovers controllers from the compiled module graph, reuses Nestpy's
canonical route compiler, and generates one immutable document during
application startup.

It does not scan packages, alter request handling, infer authorization from
guards, or add OpenAPI behavior to `StarletteAdapter`.

## Installation

Add the package with `uv`:

```text
uv add nestpy-openapi
```

The package requires Python 3.14 and uses Nestpy and msgspec. It does not add
FastAPI or Pydantic.

## Minimal Setup

Create one options value, call `OpenApiModule.for_root()`, and import the
returned descriptor into the application module.

```python
from nestpy import controller, get, module
from nestpy_openapi import OpenApiInfo, OpenApiModule, OpenApiOptions


@controller()
class HealthController:
    @get("/health")
    async def health(self) -> dict[str, str]:
        """Return process health."""
        return {"status": "ok"}


openapi_module = OpenApiModule.for_root(
    OpenApiOptions(
        info=OpenApiInfo(title="Example API", version="1.0.0"),
    )
)


@module(imports=[openapi_module], controllers=[HealthController])
class AppModule:
    pass
```

The default routes are:

| Route | Purpose |
| --- | --- |
| `GET /openapi.json` | Cached OpenAPI 3.1 JSON document |
| `GET /docs` | Cached Swagger UI HTML |

These are ordinary Nestpy controller routes. Global middleware, guards,
interceptors, filters, request scopes, request IDs, duplicate-route checks, and
normal HEAD behavior all apply.

## Runnable Example

The complete example used throughout this guide is at
`examples/nestpy/openapi/app.py`:

```python
--8<-- "examples/nestpy/openapi/app.py"
```

The example's fixed bearer token and guard exist only to demonstrate that
`api_security()` documentation and runtime enforcement are separate. Replace
them with validated authentication in a real application. Its export route also
demonstrates an opaque `HttpResponse`; current explicit metadata documents that
route's status and description, not its text body or dynamic headers.

Run it from the repository root:

```text
uv run nestpy run examples.nestpy.openapi.app:create_application
```

Then open `http://127.0.0.1:8000/docs` or request
`http://127.0.0.1:8000/openapi.json`.

## Generation Model

At startup, the module:

1. Reads controller views from `DiscoveryService`.
2. Compiles each controller through `compile_controller_routes()`.
3. Merges explicit OpenAPI metadata with route annotations.
4. Generates all schemas in one msgspec component pass.
5. Encodes and caches the JSON document and optional Swagger HTML.

Invalid Nestpy route declarations and exact duplicates fail application
compilation. OpenAPI-specific schema, normalized-path, operation-ID, and security
errors fail application startup. There is no partial or request-time fallback
document.

## Guide Map

- [Configuration](configuration.md) covers paths, servers, Swagger assets, and
  immutable options.
- [Schemas and Routes](schemas-and-routes.md) covers parameter, body, response,
  model, default, and union inference.
- [Metadata and Responses](metadata-and-responses.md) covers decorators,
  docstrings, explicit responses, headers, and opaque responses.
- [Security and Swagger UI](security-and-swagger.md) covers bearer schemes,
  public overrides, UI configuration, and deployment policy.
- [Advanced Usage](advanced.md) covers lifecycle, collisions, diagnostics,
  testing, and current limitations.
