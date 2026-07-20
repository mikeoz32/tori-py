"""The smallest Nestpy HTTP application."""

from nestpy import controller, get, module
from nestpy.starlette import NestApplication, asgi


@controller()
class HelloController:
    @get("/hello")
    async def hello(self) -> dict[str, str]:
        return {"message": "Hello, Nestpy!"}


@module(controllers=[HelloController])
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule)


application = asgi(create_application)
