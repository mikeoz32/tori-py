"""Application factory used by the supported CLI serving command."""

from nestpy import NestApplication, controller, get, module
from nestpy.starlette import StarletteAdapter


@controller()
class GreetingController:
    @get("/greeting")
    async def greeting(self) -> dict[str, str]:
        return {"message": "Serve factories with nestpy run."}


@module(controllers=[GreetingController])
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())
