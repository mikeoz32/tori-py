"""The smallest Nestpy HTTP application."""

from nestpy import NestApplication, controller, get, module
from nestpy.starlette import StarletteAdapter, asgi


@controller()
class HelloController:
    @get("/hello")
    async def hello(self) -> dict[str, str]:
        return {"message": "Hello, Nestpy!"}


@module(controllers=[HelloController])
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())


application = asgi(create_application)
