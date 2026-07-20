"""Export a synchronous ASGI3 callable from an async Nestpy factory."""

from nestpy import controller, get, module
from nestpy.starlette import NestApplication, asgi


@controller()
class HealthController:
    @get("/health")
    async def health(self) -> dict[str, str]:
        return {"status": "ok"}


@module(controllers=[HealthController])
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule)


application = asgi(create_application)
