# Security and Swagger UI

OpenAPI security metadata is explicit documentation. It does not authenticate
requests and is never inferred from ToriPy guards.

## Bearer Security Scheme

Configure named bearer components in `OpenApiOptions`:

```python
from tori_py_openapi import (
    BearerSecurityScheme,
    OpenApiInfo,
    OpenApiOptions,
)


options = OpenApiOptions(
    info=OpenApiInfo("Community API", "1.0.0"),
    security_schemes=(
        BearerSecurityScheme(
            name="oidc",
            bearer_format="JWT",
            description="OIDC access token",
        ),
    ),
)
```

Names may contain letters, digits, `.`, `_`, and `-`, and must be unique. The
current package models HTTP bearer schemes only; it does not build OAuth flow
objects.

Because HTTP bearer Security Requirement values must use an empty array in
OpenAPI 3.1, call `api_security("name")` or pass `scopes=()`. Non-empty scopes
are not an OpenAPI-compliant contract for the bearer-only schemes modeled in
this release; they are reserved for a future OAuth2 or OpenID Connect surface.

Configuring a scheme creates a component but does not add root security.

## Secured Controllers

```python
from tori_py_openapi import api_security, api_tags


@api_tags("members")
@api_security("oidc")
class MembersController:
    ...
```

Every included route inherits the controller requirement unless it declares
route-level security or `api_public()`.

Route-level declarations replace the complete controller list. Multiple
requirements are OpenAPI OR alternatives:

```python
@api_security("oidc")
@api_security("service-token")
async def read(self) -> MemberView:
    ...
```

The operation accepts `oidc` OR `service-token`; it does not require both.

Every referenced name must exist in `security_schemes`, otherwise startup fails.

## Public Override

```python
from tori_py_openapi import api_public


@api_public()
async def health(self) -> dict[str, str]:
    return {"status": "ok"}
```

On a controller with inherited security, this emits:

```json
"security": []
```

`api_public()` and `api_security()` cannot be combined on the same route.

## Runtime Authorization Is Separate

Documentation metadata does not install or configure guards:

```python
from tori_py import get, use_guard


@get("/members")
@use_guard(MemberVisibilityGuard)
@api_security("oidc")
async def list_members(self) -> list[MemberView]:
    return []
```

The guard enforces runtime policy. `api_security()` describes the client-facing
contract. Keeping these explicit avoids incorrectly documenting every guard as
authentication.

## Swagger UI Deployment

Swagger UI is precomputed during startup and served through a normal controller.
The generated HTML safely escapes the title, asset URLs, and embedded JSON
configuration.

For default CDN assets, deployment CSP must allow the pinned unpkg origin. The
generated page also contains inline bootstrap JavaScript and inline CSS. A
strict policy needs deployment-managed hashes, a nonce-bearing transformed page,
or an explicit inline policy in addition to asset origins. Derive the exact
policy from the generated page and complete application rather than copying a
generic value.

For stricter deployments, host assets yourself:

```python
from tori_py_openapi import SwaggerUiOptions


swagger_ui = SwaggerUiOptions(
    javascript_url="/assets/swagger-ui-bundle.js",
    stylesheet_url="/assets/swagger-ui.css",
    parameters={
        "deepLinking": True,
        "persistAuthorization": True,
    },
)
```

The package serves only the generated HTML. The application or reverse proxy
must serve those asset paths. Self-hosting the assets alone does not remove the
inline-script and inline-style CSP requirements.

## Protecting Documentation Routes

`/docs` and `/openapi.json` pass through normal global pipeline policy. A global
guard that denies a request also denies documentation requests. There is no
special adapter bypass or separate native-route authorization hook.

If documentation must use a different policy from product endpoints, model that
policy in normal ToriPy middleware/guard behavior using the request context and
route identity. Do not assume Swagger UI security metadata protects the route
that serves Swagger itself.
