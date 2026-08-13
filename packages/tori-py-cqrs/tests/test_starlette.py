from dataclasses import dataclass
from typing import Annotated

import pytest
from tori_py import ClassProvider, NestApplication, Query, controller, get, module
from tori_py.starlette import StarletteAdapter
from tori_py.testing import http_client
from tori_py_cqrs import CqrsModule, bind_command_handler
from tori_py_cqrs_core import Command, CommandBus


@dataclass(frozen=True, slots=True)
class Echo(Command[str]):
    value: str


class EchoHandler:
    async def handle(self, command: Echo) -> str:
        return command.value


@module(providers=[ClassProvider(EchoHandler)], exports=[EchoHandler])
class HandlersModule:
    pass


cqrs = CqrsModule.for_root(
    imports=[HandlersModule],
    handlers=[bind_command_handler(Echo, EchoHandler)],
    global_=True,
)


@controller()
class EchoController:
    def __init__(self, commands: CommandBus) -> None:
        self.commands = commands

    @get("/echo")
    async def echo(self, value: Annotated[str, Query("value")]) -> str:
        return await self.commands.execute(Echo(value))


@module(imports=[cqrs], controllers=[EchoController])
class AppModule:
    pass


@pytest.mark.asyncio
async def test_starlette_adapter_and_cqrs_module_coexist() -> None:
    application = await NestApplication.create(AppModule, adapter=StarletteAdapter())
    await application.start()
    try:
        async with http_client(application) as client:
            response = await client.get("/echo", params={"value": "integrated"})
    finally:
        await application.shutdown()

    assert response.status_code == 200
    assert response.json() == "integrated"
