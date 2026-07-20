"""Load one typed settings model through a global SettingsModule."""

from pathlib import Path

import msgspec
from nestpy import controller, get, module
from nestpy.settings import SettingsModule, SettingsOptions
from nestpy.starlette import NestApplication


class GreetingSettings(msgspec.Struct):
    greeting: str = "Hello from settings"


@controller()
class GreetingController:
    def __init__(self, settings: GreetingSettings) -> None:
        self._settings = settings

    @get("/greeting")
    async def greeting(self) -> dict[str, str]:
        return {"message": self._settings.greeting}


settings_module = SettingsModule.for_root(
    SettingsOptions(
        model=GreetingSettings,
        base_dir=Path(__file__).parent,
        environment={},
    ),
    global_=True,
)


@module(imports=[settings_module], controllers=[GreetingController])
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule)
