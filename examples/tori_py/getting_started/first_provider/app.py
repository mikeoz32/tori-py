"""Inject a class provider into a controller constructor."""

from tori_py import NestApplication, controller, get, injectable, module
from tori_py.starlette import StarletteAdapter


@injectable()
class GreetingService:
    def message(self) -> str:
        return "Providers are explicit constructor dependencies."


@controller()
class GreetingController:
    def __init__(self, greeting: GreetingService) -> None:
        self._greeting = greeting

    @get("/greeting")
    async def greeting(self) -> dict[str, str]:
        return {"message": self._greeting.message()}


@module(
    providers=[GreetingService],
    controllers=[GreetingController],
)
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())
