"""Show that application creation compiles before lifecycle startup."""

from tori_py import NestApplication, controller, get, module
from tori_py.starlette import StarletteAdapter


@controller()
class StatusController:
    @get("/status")
    async def status(self) -> dict[str, str]:
        return {"status": "ready after lifespan startup"}


@module(controllers=[StatusController])
class AppModule:
    pass


async def create_application() -> NestApplication:
    """Return an unstarted application for an ASGI server to start."""

    return await NestApplication.create(AppModule, adapter=StarletteAdapter())
