"""Application factory used by the supported CLI serving command."""

from nestpy import controller, get, module
from nestpy.starlette import NestApplication


@controller()
class GreetingController:
    @get("/greeting")
    async def greeting(self) -> dict[str, str]:
        return {"message": "Serve factories with nestpy run."}


@module(controllers=[GreetingController])
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule)
