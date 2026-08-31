from typing import Annotated

from starlette.websockets import WebSocket
from tori_py import (
    Inject,
    NestApplication,
    Path,
    Scope,
    Socket,
    injectable,
    module,
    websocket_gateway,
)
from tori_py.starlette import StarletteAdapter, asgi


@injectable(scope=Scope.REQUEST)
class ConnectionState:
    def __init__(self) -> None:
        self.message_count = 0


@websocket_gateway("/echo/{channel}")
class EchoGateway:
    async def handle(
        self,
        socket: Annotated[WebSocket, Socket()],
        channel: Annotated[str, Path("channel")],
        state: Annotated[ConnectionState, Inject(ConnectionState)],
    ) -> None:
        await socket.accept()
        message = await socket.receive_text()
        state.message_count += 1
        await socket.send_text(f"{channel}:{state.message_count}:{message}")
        await socket.close()


@module(providers=[EchoGateway, ConnectionState])
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())


application = asgi(create_application)
