"""Application used by the first TestingModule example."""

from typing import Annotated

from nestpy import Inject, ValueProvider, controller, get, module

GREETING = "greeting"


@controller()
class GreetingController:
    def __init__(self, greeting: Annotated[str, Inject(GREETING)]) -> None:
        self._greeting = greeting

    @get("/greeting")
    async def greeting(self) -> dict[str, str]:
        return {"message": self._greeting}


@module(
    providers=[ValueProvider(GREETING, "Hello from production")],
    controllers=[GreetingController],
    exports=[GREETING],
)
class AppModule:
    pass
