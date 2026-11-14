"""Drive a page over Phoenix V2 Channel frames, one frame at a time."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from typing import Any, cast

import httpx
import pytest_asyncio
from starlette.types import ASGIApp, Message
from tori_py import ModuleImport, NestApplication, module
from tori_py.starlette import StarletteAdapter
from tori_py_liveview import LiveView, LiveViewModule, LiveViewOptions
from tori_py_liveview_ui import LiveViewUiModule

_TOPIC = "lv:tori-live-root"
_SOCKET = "/_tori/live/websocket"


def _scope() -> Any:
    return {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.5"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": _SOCKET,
        "raw_path": _SOCKET.encode(),
        "query_string": b"",
        "headers": [(b"host", b"testserver"), (b"origin", b"http://testserver")],
        "client": ("test", 1),
        "server": ("testserver", 80),
        "subprotocols": [],
    }


class Channel:
    """One browser connection to a page of a test application."""

    def __init__(self, asgi: ASGIApp, path: str) -> None:
        self._asgi = asgi
        self._path = path
        self._incoming: asyncio.Queue[Message] = asyncio.Queue()
        self._changed = asyncio.Event()
        self._task: asyncio.Future[None] | None = None
        self._ref = 1
        self.sent: list[Message] = []
        self.document = ""

    async def get(self) -> str:
        """Fetch the page over HTTP, as the first request of a browser does."""
        transport = httpx.ASGITransport(app=self._asgi)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.get(self._path)
        assert response.status_code == 200, response.text
        self.document = response.text
        return self.document

    async def join(self) -> dict[str, Any]:
        """Open the socket and join; returns the first rendered tree."""
        token = re.search(r'data-phx-session="([A-Za-z0-9_.-]+)"', await self.get())
        assert token is not None
        await self._incoming.put({"type": "websocket.connect"})

        async def send(message: Message) -> None:
            self.sent.append(message)
            self._changed.set()

        self._task = asyncio.ensure_future(
            self._asgi(_scope(), self._incoming.get, send)
        )
        await self._push(
            [
                "1",
                "1",
                _TOPIC,
                "phx_join",
                {
                    "url": f"http://testserver{self._path}",
                    "params": {"_mounts": 0, "_mount_attempts": 0},
                    "session": token[1],
                    "static": None,
                    "sticky": False,
                },
            ]
        )
        return cast(dict[str, Any], (await self._reply("1"))["rendered"])

    async def event(self, name: str, value: object = None) -> dict[str, Any]:
        """Push a browser event and return the response to it."""
        self._ref += 1
        ref = str(self._ref)
        await self._push(
            [
                "1",
                ref,
                _TOPIC,
                "event",
                {"type": "click", "event": name, "value": value or {}},
            ]
        )
        return await self._reply(ref)

    @property
    def frames(self) -> list[list[Any]]:
        return [
            json.loads(cast(str, message["text"]))
            for message in self.sent
            if message["type"] == "websocket.send"
        ]

    @property
    def pushes(self) -> list[dict[str, Any]]:
        """The diffs the server sent without a browser event asking for one."""
        return [frame[4] for frame in self.frames if frame[3] == "diff"]

    @property
    def close_code(self) -> int | None:
        """The code the server closed the socket with, if it did."""
        for message in self.sent:
            if message["type"] == "websocket.close":
                return cast(int, message["code"])
        return None

    async def until(self, condition: Callable[[], bool], timeout: float = 3.0) -> None:
        """Wait for a condition on the frames or on state a test observes."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not condition():
            if loop.time() > deadline:
                raise AssertionError("the condition was not met in time")
            self._changed.clear()
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=0.01)
            except TimeoutError:
                pass

    async def close(self) -> None:
        """Disconnect, as a browser that leaves does."""
        if self._task is None or self._task.done():
            return
        await self._incoming.put(
            {"type": "websocket.disconnect", "code": 1000, "reason": ""}
        )
        await asyncio.wait_for(self._task, timeout=10)

    async def _push(self, frame: list[object]) -> None:
        await self._incoming.put(
            {"type": "websocket.receive", "text": json.dumps(frame)}
        )

    async def _reply(self, ref: str) -> dict[str, Any]:
        def replies() -> list[list[Any]]:
            return [
                frame
                for frame in self.frames
                if frame[3] == "phx_reply" and frame[1] == ref
            ]

        await self.until(lambda: bool(replies()))
        payload = replies()[0][4]
        assert payload["status"] == "ok", payload
        return cast(dict[str, Any], payload["response"])


type OpenPage = Callable[..., Awaitable[Channel]]


@pytest_asyncio.fixture
async def open_page() -> AsyncIterator[OpenPage]:
    """Serve one page class and return a joined connection to it."""
    applications: list[NestApplication] = []
    channels: list[Channel] = []

    async def open(
        page: type[LiveView],
        *,
        imports: Iterable[ModuleImport] = (),
        join: bool = True,
    ) -> Channel:
        liveview = LiveViewModule.for_root(
            LiveViewOptions(secret="s" * 32, async_cancel_timeout_seconds=0.5),
            pages=[page],
            imports=imports,
        )

        @module(imports=[liveview, LiveViewUiModule.for_root()])
        class Root:
            pass

        application = await NestApplication.create(Root, adapter=StarletteAdapter())
        await application.start()
        applications.append(application)
        routes = page.__dict__["__tori_py_liveview_routes__"]
        channel = Channel(application.get_adapter(StarletteAdapter).app, routes[0].path)
        channels.append(channel)
        if join:
            await channel.join()
        return channel

    yield open
    for channel in channels:
        await channel.close()
    for application in applications:
        await application.shutdown()
