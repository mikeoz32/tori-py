"""Export a synchronous ASGI3 callable from an async ToriPy factory."""

from tori_py import NestApplication, controller, get, module
from tori_py.starlette import StarletteAdapter, asgi


@controller()
class HealthController:
    @get("/health")
    async def health(self) -> dict[str, str]:
        return {"status": "ok"}


class AllowAllGuard:
    async def can_activate(self, context) -> bool:
        return True


@module(controllers=[HealthController])
class AppModule:
    pass


async def create_application() -> NestApplication:
    application = await NestApplication.create(AppModule, adapter=StarletteAdapter())
    return application.use_global_guard(AllowAllGuard())


application = asgi(create_application)
