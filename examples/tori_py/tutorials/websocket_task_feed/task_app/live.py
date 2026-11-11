"""WebSocket gateway that streams created tasks to connected clients."""

import asyncio
from contextlib import AbstractAsyncContextManager
from typing import Annotated

import msgspec
from starlette.websockets import WebSocket
from tori_py import Inject, Socket, use_guards, websocket_gateway
from tori_py.starlette import WebSocketRequestContext

from .feed import TaskFeed
from .models import Task
from .services import TaskService

TASK_WAKEUP = "task-wakeup"
ALLOWED_ORIGINS = frozenset({"http://127.0.0.1:8000", "http://localhost:8000"})


class Snapshot(msgspec.Struct, tag_field="type", tag="snapshot"):
    tasks: list[Task]


class Created(msgspec.Struct, tag_field="type", tag="created"):
    task: Task


def subscribe(feed: TaskFeed) -> AbstractAsyncContextManager[asyncio.Event]:
    return feed.subscribe()


class BrowserOriginGuard:
    """Reject browser pages from other sites; allow clients without an Origin."""

    async def can_activate(self, context: WebSocketRequestContext) -> bool:
        origin = context.socket.headers.get("origin")
        return origin is None or origin in ALLOWED_ORIGINS


@websocket_gateway("/tasks/live")
@use_guards(BrowserOriginGuard)
class TaskFeedGateway:
    def __init__(self, tasks: TaskService) -> None:
        self._tasks = tasks

    async def handle(
        self,
        socket: Annotated[WebSocket, Socket()],
        wakeup: Annotated[asyncio.Event, Inject(TASK_WAKEUP)],
    ) -> None:
        await socket.accept()
        async with asyncio.TaskGroup() as group:
            sender = group.create_task(self._send_tasks(socket, wakeup))
            await _receive_until_disconnect(socket)
            sender.cancel()

    async def _send_tasks(self, socket: WebSocket, wakeup: asyncio.Event) -> None:
        tasks = self._tasks.all()
        await _send(socket, Snapshot(tasks))
        last_id = tasks[-1].id if tasks else 0
        while True:
            await wakeup.wait()
            wakeup.clear()
            for task in self._tasks.created_after(last_id):
                await _send(socket, Created(task))
                last_id = task.id


async def _send(socket: WebSocket, message: Snapshot | Created) -> None:
    await socket.send_text(msgspec.json.encode(message).decode())


async def _receive_until_disconnect(socket: WebSocket) -> None:
    while (await socket.receive())["type"] != "websocket.disconnect":
        pass
