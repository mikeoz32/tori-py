"""The smallest ToriPy HTTP application."""

from tori_py import NestApplication, controller, get, module
from tori_py.starlette import StarletteAdapter, asgi


@controller()
class HelloController:
    @get("/hello")
    async def hello(self) -> dict[str, str]:
        return {"message": "Hello, ToriPy!"}


@module(controllers=[HelloController])
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())


application = asgi(create_application)
