from __future__ import annotations

import asyncio
import re
import socket
import threading
import time
from collections.abc import Coroutine, Iterator, Mapping
from typing import Any, cast

import pytest
import uvicorn
from playwright.sync_api import Page, Request, expect
from pytest_bdd import given, parsers, scenarios, then, when
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

scenarios("features/liveview_browser.feature")


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
            '<a id="anchor-edit" data-phx-link="redirect" '
            'data-phx-link-state="push" href="/browser-nav/edit">'
            "Anchor edit</a>"
        )

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "edit":
            raise UnknownEventError(event)
        self.push_navigate("/browser-nav/edit")


_ECHO_HOOK = """<script>
globalThis.ToriLiveHooks = {
  Echo: {
    mounted() {
      this.handleEvent("server-said", ({text}) => { this.el.dataset.server = text; });
      this.pushEvent("hook-ping", {n: 41}, (reply) => {
        this.el.textContent = String(reply.n);
      });
    },
  },
};
</script>"""


@live_view("/browser-hooks")
class BrowserHooksLive(LiveView):
    def __init__(self) -> None:
        self.pings = 0

    async def handle_event(self, event: str, value: object) -> Mapping[str, object]:
        if event != "hook-ping" or not isinstance(value, dict):
            raise UnknownEventError(event)
        count = cast(dict[str, object], value)["n"]
        assert isinstance(count, int)
        self.pings += 1
        self.push_event("server-said", {"text": f"pong {self.pings}"})
        return {"n": count + 1}

    def render(self) -> str:
        return (
            '<div id="hooked" phx-hook="Echo" phx-update="ignore"></div>'
            f'<output id="pings">{self.pings}</output>'
        )

    def render_document(self, live_root: str, client_script: str) -> str:
        return super().render_document(live_root, _ECHO_HOOK + client_script)


def _asgi(application: NestApplication) -> ASGIApp:
    return application.get_adapter(StarletteAdapter).app


async def _create_application() -> NestApplication:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[BrowserCounterLive, BrowserNavigationLive, BrowserHooksLive],
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


@given(
    parsers.parse('I open the "{path}" live page'),
    target_fixture="document_requests",
)
def open_live_page(page: Page, live_server: str, path: str) -> list[str]:
    requests: list[str] = []

    def record(request: Request) -> None:
        if request.is_navigation_request():
            requests.append(request.url)

    page.on("request", record)
    page.goto(f"{live_server}{path}")
    expect(page.locator("[data-phx-main]")).to_have_class(
        re.compile(r"\bphx-connected\b")
    )
    return requests


@when(parsers.parse('I click "{selector}"'), target_fixture="requests_before_click")
def click(page: Page, document_requests: list[str], selector: str) -> int:
    count = len(document_requests)
    page.locator(selector).click()
    return count


@given(parsers.parse('"{selector}" shows "{text}"'))
@then(parsers.parse('"{selector}" shows "{text}"'))
def shows(page: Page, selector: str, text: str) -> None:
    expect(page.locator(selector)).to_have_text(text)


@then(parsers.parse('"{selector}" has "{name}" set to "{value}"'))
def has_attribute(page: Page, selector: str, name: str, value: str) -> None:
    expect(page.locator(selector)).to_have_attribute(name, value)


@then(parsers.parse('the URL is "{path}"'))
def url_is(page: Page, live_server: str, path: str) -> None:
    expect(page).to_have_url(f"{live_server}{path}")


@then("the document was not reloaded")
def document_not_reloaded(
    document_requests: list[str], requests_before_click: int
) -> None:
    assert len(document_requests) == requests_before_click
