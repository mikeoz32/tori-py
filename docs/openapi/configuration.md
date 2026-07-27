# OpenAPI Configuration

`OpenApiOptions` and its nested values are frozen, slotted dataclasses. Inputs
are validated and copied during construction so startup generation cannot be
changed by later mutation.

## Core Options

```python
from nestpy_openapi import (
    OpenApiInfo,
    OpenApiModule,
    OpenApiOptions,
    OpenApiServer,
)


openapi_module = OpenApiModule.for_root(
    OpenApiOptions(
        info=OpenApiInfo(
            title="Community API",
            version="2.1.0",
            description="Public HTTP API for community clients.",
        ),
        openapi_path="/schema/openapi.json",
        docs_path="/reference",
        servers=(
            OpenApiServer("https://api.example.com", "Production"),
            OpenApiServer("/", "Current deployment"),
        ),
    )
)
```

| Option | Default | Behavior |
| --- | --- | --- |
| `info` | required | Root title, version, and optional description |
| `openapi_path` | `/openapi.json` | Static route for the JSON document |
| `docs_path` | `/docs` | Static Swagger route; `None` disables UI |
| `servers` | `()` | Ordered absolute or relative server URLs |
| `security_schemes` | `()` | Named bearer security components |
| `swagger_ui` | `SwaggerUiOptions()` | Asset URLs and client parameters |

`OpenApiModule.for_root(options, key="default")` returns a normal keyed
`DeferredModule`. Most applications configure one descriptor and import it once
at the root.

## Documentation Paths

Documentation paths must:

- begin with exactly one `/`;
- be static, without `{}` variables;
- contain no query, fragment, backslash, whitespace, or control characters;
- differ from each other.

Application route conflicts are handled by normal Nestpy route compilation. For
example, an application controller cannot also own `GET /docs` while the default
Swagger route is enabled.

Disable only Swagger UI while retaining machine-readable JSON:

```python
options = OpenApiOptions(
    info=OpenApiInfo("Internal API", "1.0.0"),
    docs_path=None,
)
```

The OpenAPI JSON route cannot be disabled independently in this release.

## Servers

Server URLs may be absolute or relative:

```python
servers = (
    OpenApiServer("https://api.example.com/v1", "Production"),
    OpenApiServer("/v1", "Current host"),
)
```

Malformed hosts, ports, percent escapes, backslashes, whitespace, controls, and
server template variables are rejected. Server variables are not modeled by the
current `OpenApiServer` value.

## Swagger UI Options

Swagger UI uses pinned `swagger-ui-dist` 5.31.0 CDN assets by default. Customize
only client behavior:

```python
from nestpy_openapi import SwaggerUiOptions


swagger_ui = SwaggerUiOptions(
    parameters={
        "deepLinking": True,
        "persistAuthorization": True,
        "displayRequestDuration": True,
    }
)
```

The parameter mapping is JSON-normalized, defensively copied, and recursively
frozen. The following keys are package-owned and cannot be supplied:

```text
url
urls
spec
dom_id
```

Host assets in the application when network policy does not allow the default
CDN:

```python
swagger_ui = SwaggerUiOptions(
    javascript_url="/assets/swagger-ui-bundle.js",
    stylesheet_url="/assets/swagger-ui.css",
)
```

Asset URLs must be absolute HTTPS URLs or root-relative paths. HTTP,
protocol-relative, `data:`, `javascript:`, malformed, and backslash-containing
URLs fail configuration.

Self-hosting removes the external asset origins, but the generated page still
contains inline bootstrap JavaScript and inline CSS. A strict CSP therefore also
needs deployment-managed hashes, a transformed nonce-bearing page, or an
explicit inline policy. `SwaggerUiOptions` does not currently configure CSP
nonces.

## Configuration Errors

Invalid options raise `OpenApiConfigurationError` immediately. Invalid metadata
decorator arguments raise `OpenApiMetadataError` when declarations execute.
Nestpy route signatures, unresolved handler annotations, and exact duplicate
routes can raise `BootstrapError` during `NestApplication.create()`. OpenAPI-only
schema, normalized-path, component, operation-ID, and security checks raise
`OpenApiSchemaError` during application startup. These errors expose the normal
Nestpy diagnostic code and details contract.
