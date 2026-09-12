from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Coroutine, Iterator
from typing import Any

import pytest
import uvicorn
from playwright.sync_api import Page, expect
from starlette.types import ASGIApp
from tori_py import NestApplication, module
from tori_py.starlette import StarletteAdapter
from tori_py_liveview import (
    LiveView,
    LiveViewModule,
    LiveViewOptions,
    MountContext,
    UnknownEventError,
    live_view,
)

pytestmark = pytest.mark.browser


@live_view("/browser-counter")
class BrowserCounterLive(LiveView):
    def __init__(self) -> None:
        self.connected_mount = False
        self.count = 0

    async def mount(self, context: MountContext) -> None:
        self.connected_mount = context.connected

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "increment":
            raise UnknownEventError(event)
        self.count += 1

    def render(self) -> str:
        state = "connected" if self.connected_mount else "disconnected"
        return (
            f'<output id="connection">{state}</output>'
            f'<button id="increment" phx-click="increment">+</button>'
            f'<output id="count">{self.count}</output>'
        )


@live_view("/browser-nav", action="index")
@live_view("/browser-nav/edit", action="edit")
class BrowserNavigationLive(LiveView):
    def render(self) -> str:
        return (
            f'<output id="action">{self.live_action}</output>'
            '<button id="edit" phx-click="edit">Edit</button>'
        )

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "edit":
            raise UnknownEventError(event)
        self.push_navigate("/browser-nav/edit")


def _asgi(application: NestApplication) -> ASGIApp:
    return application.get_adapter(StarletteAdapter).app


async def _create_application() -> NestApplication:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[BrowserCounterLive, BrowserNavigationLive],
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    return application


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    result: list[T] = []
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(coroutine))
        except BaseException as exception:
            error.append(exception)

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


@pytest.fixture
def live_server() -> Iterator[str]:
    application = _run_async(_create_application())
    server = uvicorn.Server(
        uvicorn.Config(
            _asgi(application),
            host="127.0.0.1",
            port=_free_port(),
            log_level="error",
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("Uvicorn failed to start")
        if time.monotonic() >= deadline:
            server.should_exit = True
            thread.join(timeout=10)
            raise TimeoutError("Timed out waiting for Uvicorn to start")
        time.sleep(0.01)

    try:
        port = server.config.port
        assert port is not None
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        _run_async(application.shutdown())


def test_browser_mounts_liveview_and_handles_event(
    page: Page,
    live_server: str,
) -> None:
    page.goto(f"{live_server}/browser-counter")

    expect(page.locator("#connection")).to_have_text("connected")
    expect(page.locator("#count")).to_have_text("0")

    page.locator("#increment").click()

    expect(page.locator("#count")).to_have_text("1")


def test_browser_push_navigate_rejoins_without_document_reload(
    page: Page,
    live_server: str,
) -> None:
    document_requests: list[str] = []
    page.on(
        "request",
        lambda request: (
            document_requests.append(request.url)
            if request.is_navigation_request()
            else None
        ),
    )
    page.goto(f"{live_server}/browser-nav")

    expect(page.locator("#action")).to_have_text("index")
    expect(page.locator("#edit")).to_be_visible()
    document_request_count = len(document_requests)

    page.locator("#edit").click()

    expect(page).to_have_url(f"{live_server}/browser-nav/edit")
    expect(page.locator("#action")).to_have_text("edit")
    assert len(document_requests) == document_request_count
