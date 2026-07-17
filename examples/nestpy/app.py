"""Minimal documented Nestpy HTTP application."""

from pathlib import Path
from typing import Annotated

import msgspec
from nestpy import (
    FactoryProvider,
    Inject,
    PipelineResult,
    Query,
    Scope,
    StarletteOptions,
    ValueProvider,
    controller,
    get,
    module,
    use_guards,
)
from nestpy.settings import SettingsModule, SettingsOptions
from nestpy.starlette import MsgspecValidationPipe, NestApplication
from starlette.responses import Response


class AppSettings(msgspec.Struct):
    greeting: str = "hello"


class AllowGuard:
    async def can_activate(self, context) -> bool:
        return True


class ExampleFilter:
    async def catch(self, error, context) -> PipelineResult:
        return PipelineResult.from_response(Response("example error", status_code=500))


@controller("/example")
class ExampleController:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    @get("/health")
    @use_guards("allow")
    async def health(
        self,
        count: Annotated[int, Query("count")],
        request_value: Annotated[str, Inject("request_value")],
    ) -> dict[str, object]:
        return {
            "status": self.settings.greeting,
            "count": count,
            "request_value": request_value,
        }


settings = SettingsModule.for_root(
    SettingsOptions(model=AppSettings, base_dir=Path(__file__).parent),
    global_=True,
)


@module(
    imports=[settings],
    controllers=[ExampleController],
    providers=[
        FactoryProvider("request_value", lambda: "request", scope=Scope.REQUEST),
        ValueProvider("allow", AllowGuard()),
        ValueProvider("validation", MsgspecValidationPipe()),
        ValueProvider("errors", ExampleFilter()),
    ],
)
class AppModule:
    pass


async def create_application() -> NestApplication:
    """Return a compiled application; the ASGI wrapper owns startup."""

    return await NestApplication.create(
        AppModule,
        http=StarletteOptions(pipes=("validation",), filters=("errors",)),
    )
