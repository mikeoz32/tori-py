# tori-py-openapi

`tori-py-openapi` is the optional OpenAPI 3.1 documentation integration for
ToriPy. It discovers ToriPy controllers, compiles their transport-neutral route
mappings, and serves a cached document with an optional Swagger UI.

```python
from typing import Annotated

from tori_py import Path, controller, get, module
from tori_py_openapi import (
    BearerSecurityScheme,
    OpenApiInfo,
    OpenApiModule,
    OpenApiOptions,
    api_operation,
    api_security,
    api_tags,
)


@controller("/members")
@api_tags("members")
class MembersController:
    @get("/{member_id}")
    @api_operation(summary="Read a member profile")
    @api_security("oidc")
    async def get_profile(
        self,
        member_id: Annotated[str, Path("member_id")],
    ) -> dict[str, str]:
        """Return the public profile fields visible to the current member.

        \f
        Internal implementation notes stay out of the OpenAPI description.
        """
        return {"member_id": member_id}


openapi_module = OpenApiModule.for_root(
    OpenApiOptions(
        info=OpenApiInfo(title="Example API", version="0.1.0"),
        security_schemes=(BearerSecurityScheme(name="oidc"),),
    )
)


@module(imports=[openapi_module], controllers=[MembersController])
class AppModule:
    pass
```

Decorators attach immutable metadata directly to their class or function. They
perform no registration and do not install guards. The documentation endpoints
are ordinary ToriPy controller routes, so guards, pipes, interceptors, filters,
request scope, and request-ID middleware apply normally.

When `api_operation(description=...)` is omitted, the cleaned route docstring up
to the first `\f` becomes the operation description. Summaries remain explicit.

Swagger UI uses pinned CDN assets by default. Deployments must allow those asset
origins in network and CSP policy or configure application-hosted root-relative
asset URLs with `SwaggerUiOptions`.
