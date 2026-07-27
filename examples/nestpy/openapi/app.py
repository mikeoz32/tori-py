"""Documented member API used by the Nestpy OpenAPI guide."""

from typing import Annotated, Literal

import msgspec
from nestpy import (
    HttpResponse,
    NestApplication,
    Path,
    Query,
    controller,
    get,
    header,
    module,
    use_guard,
    use_pipe,
)
from nestpy.http import MsgspecValidationPipe
from nestpy.starlette import RequestContext, StarletteAdapter, asgi
from nestpy_openapi import (
    BearerSecurityScheme,
    OpenApiInfo,
    OpenApiModule,
    OpenApiOptions,
    OpenApiServer,
    SwaggerUiOptions,
    api_operation,
    api_public,
    api_response,
    api_security,
    api_tags,
)


class MemberView(msgspec.Struct):
    handle: str
    display_name: str
    detail: Literal["summary", "full"]


class Problem(msgspec.Struct):
    detail: str


class DemoBearerGuard:
    """Demonstrate enforcement only; production uses validated OIDC claims."""

    async def can_activate(self, context: RequestContext) -> bool:
        return context.headers.get("authorization") == "Bearer example-token"


@controller("/members")
@api_tags("members")
@api_security("oidc")
@use_guard(DemoBearerGuard)
@use_pipe(MsgspecValidationPipe())
class MembersController:
    @get("/{handle}")
    @header("Cache-Control", "private, no-store")
    @api_operation(summary="Read a member", operation_id="members_read")
    @api_response(404, description="Member not found", model=Problem)
    async def read(
        self,
        handle: Annotated[str, Path("handle")],
        detail: Annotated[Literal["summary", "full"], Query("detail")] = "summary",
    ) -> MemberView:
        """Return the member fields visible to the current caller.

        The optional detail mode controls the amount of profile information.

        \f
        Internal authorization and storage notes are not published.
        """
        return MemberView(
            handle=handle,
            display_name=handle.replace("-", " ").title(),
            detail=detail,
        )

    @get("/{handle}/export")
    @api_operation(summary="Export a member profile")
    @api_response(200, description="UTF-8 profile export")
    async def export(
        self,
        handle: Annotated[str, Path("handle")],
    ) -> HttpResponse:
        return HttpResponse(
            f"member={handle}\n".encode(),
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )


@controller()
@api_tags("system")
@api_security("oidc")
class SystemController:
    @get("/health")
    @api_public()
    @api_operation(summary="Check process health")
    async def health(self) -> dict[str, str]:
        return {"status": "ok"}


openapi_module = OpenApiModule.for_root(
    OpenApiOptions(
        info=OpenApiInfo(
            title="Documented Member API",
            version="1.0.0",
            description="Runnable nestpy-openapi example.",
        ),
        servers=(OpenApiServer("/", "Current deployment"),),
        security_schemes=(
            BearerSecurityScheme(
                "oidc",
                bearer_format="JWT",
                description="OIDC access token",
            ),
        ),
        swagger_ui=SwaggerUiOptions(
            parameters={"deepLinking": True, "persistAuthorization": True}
        ),
    )
)


@module(
    imports=[openapi_module],
    controllers=[MembersController, SystemController],
)
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())


application = asgi(create_application)
