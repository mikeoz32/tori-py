"""Application factory used by the supported CLI serving command."""

from tori_py import NestApplication, controller, get, module
from tori_py.starlette import StarletteAdapter


@controller()
class GreetingController:
    @get("/greeting")
    async def greeting(self) -> dict[str, str]:
        return {"message": "Serve factories with tori-py run."}


@module(controllers=[GreetingController])
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())
