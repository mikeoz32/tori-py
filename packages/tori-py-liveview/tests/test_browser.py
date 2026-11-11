from __future__ import annotations

import asyncio
import json
import re
import socket
import threading
import time
from collections.abc import Callable, Coroutine, Iterator, Mapping
from typing import Any, cast
from urllib.parse import parse_qsl, urlsplit

import pytest
import uvicorn
from playwright.sync_api import Page, Request, Response, WebSocket, expect
from pytest_bdd import given, parsers, scenarios, then, when
from starlette.types import ASGIApp
from tori_py import NestApplication, module
from tori_py.http import HttpException
from tori_py.starlette import StarletteAdapter
from tori_py_liveview import (
    AsyncResult,
    LiveComponent,
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


@live_view("/browser-flash", action="index")
@live_view("/browser-flash/next", action="next")
@live_view("/browser-flash/hop", action="hop")
class BrowserFlashLive(LiveView):
    async def mount(self, context: MountContext) -> None:
        del context
        # The hop page moves on while mounting, over HTTP and when connected.
        if self.live_action == "hop":
            self.push_navigate("/browser-flash/next")

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event == "save":
            self.put_flash("info", "Saved")
        elif event == "navigate":
            self.put_flash("info", "Moved")
            self.push_navigate("/browser-flash/next")
        elif event == "leave":
            self.put_flash("info", "Left")
            self.redirect("/browser-flash/next")
        elif event == "hop":
            self.put_flash("info", "Hopped")
            self.push_navigate("/browser-flash/hop")
        elif event == "hop-reload":
            self.put_flash("info", "Hopped over HTTP")
            self.redirect("/browser-flash/hop")
        else:
            raise UnknownEventError(event)

    def render(self):
        info = self.flash.get("info", "")
        return (
            t'<p id="flash-info" phx-click="lv:clear-flash" phx-value-key="info">'
            t"{info}</p>"
            t'<button id="save" phx-click="save">Save</button>'
            t'<button id="navigate" phx-click="navigate">Navigate</button>'
            t'<button id="leave" phx-click="leave">Leave</button>'
            t'<button id="hop" phx-click="hop">Hop</button>'
            t'<button id="hop-reload" phx-click="hop-reload">Hop over HTTP</button>'
        )


@live_view("/browser-async")
class BrowserAsyncLive(LiveView):
    def __init__(self) -> None:
        self.org: AsyncResult[object] = AsyncResult()
        self.release = asyncio.Event()

    async def mount(self, context: MountContext) -> None:
        del context
        self.assign_async("org", self.load_org)

    async def load_org(self) -> object:
        await self.release.wait()
        return "Acme"

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "release":
            raise UnknownEventError(event)
        self.release.set()

    def render(self):
        text = "loading" if self.org.loading else str(self.org.result)
        return (
            t'<output id="org">{text}</output>'
            t'<button id="release" phx-click="release">Release</button>'
        )


_CONNECT_PARAMS = (
    '<script>globalThis.ToriLiveParams = {locale: "uk"};</script>'
    '<a phx-track-static href="/assets/app-1.css" hidden></a>'
)


@live_view("/browser-params", action="index")
@live_view("/browser-params/next", action="next")
class BrowserParamsLive(LiveView):
    def __init__(self) -> None:
        self.values = dict.fromkeys(("locale", "mounts", "referer", "same", "new"), "-")

    async def mount(self, context: MountContext) -> None:
        params = context.connect_params
        if params is None:
            return
        same = context.static_changed(["/assets/app-1.css"])
        new = context.static_changed(["/assets/app-2.css"])
        self.values = {
            "locale": str(params.get("locale")),
            "mounts": str(params.get("_mounts")),
            "referer": str(params.get("_live_referer", "-")),
            "same": "changed" if same else "unchanged",
            "new": "changed" if new else "unchanged",
        }

    def render(self):
        values = self.values
        return (
            t'<output id="locale">{values["locale"]}</output>'
            t'<output id="mounts">{values["mounts"]}</output>'
            t'<output id="referer">{values["referer"]}</output>'
            t'<output id="static-same">{values["same"]}</output>'
            t'<output id="static-new">{values["new"]}</output>'
            t'<a id="next" data-phx-link="redirect" data-phx-link-state="push" '
            t'href="/browser-params/next">Next</a>'
        )

    def render_document(self, live_root: str, client_script: str) -> str:
        return super().render_document(_CONNECT_PARAMS + live_root, client_script)


@live_view("/browser-gone")
class BrowserGoneLive(LiveView):
    async def mount(self, context: MountContext) -> None:
        # Only the connected mount fails, as when data loads only once
        # connected, so the HTTP render alone would succeed on every reload.
        if context.connected:
            raise HttpException(404, "gone")

    def render(self) -> str:
        return "<p>here</p>"


class BrowserCard(LiveComponent):
    def __init__(self) -> None:
        self.count = 0

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "bump":
            raise UnknownEventError(event)
        self.count += 1

    def render(self):
        return (
            t'<section id="{self.id}-card">'
            t'<output id="{self.id}-count">{self.count}</output>'
            t'<button id="{self.id}-bump" phx-click="bump" '
            t'phx-target="{self.myself}">+</button>'
            t"</section>"
        )


@live_view("/browser-diff")
class BrowserDiffLive(LiveView):
    def __init__(self) -> None:
        self.count = 0
        self.show_right = True
        self.items = 0

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event == "bump":
            self.count += 1
        elif event == "toggle":
            self.show_right = not self.show_right
        elif event == "blink":
            # Leave the right card out of this render and bring it back in the
            # next one, before the client can confirm its destruction.
            self.show_right = False
            self.send_info("show-right")
        elif event == "add":
            self.items += 1
            item = f"item-{self.items}"
            self.stream_insert("items", item, t'<li id="{item}">{item}</li>')
        else:
            raise UnknownEventError(event)

    async def handle_info(self, name: str, value: object) -> None:
        if name != "show-right":
            await super().handle_info(name, value)
            return
        self.show_right = True

    def title(self) -> str:
        return f"Clicks {self.count}"

    def render(self):
        left = self.live_component(BrowserCard, "left")
        right = self.live_component(BrowserCard, "right") if self.show_right else ""
        return (
            t'<output id="page-count">{self.count}</output>'
            t'<button id="bump" phx-click="bump">+</button>'
            t'<button id="toggle" phx-click="toggle">Toggle</button>'
            t'<button id="blink" phx-click="blink">Blink</button>'
            t'<button id="add" phx-click="add">Add</button>'
            t"{left}{right}"
            t'<ul id="items" phx-update="stream">{self.stream_contents("items")}</ul>'
        )


def _asgi(application: NestApplication) -> ASGIApp:
    return application.get_adapter(StarletteAdapter).app


async def _create_application() -> NestApplication:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[
            BrowserCounterLive,
            BrowserNavigationLive,
            BrowserHooksLive,
            BrowserFlashLive,
            BrowserAsyncLive,
            BrowserParamsLive,
            BrowserGoneLive,
            BrowserDiffLive,
        ],
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


@pytest.fixture
def socket_frames(page: Page) -> list[list[Any]]:
    """Channel frames the server sent to the page."""
    frames: list[list[Any]] = []

    def watch(socket: WebSocket) -> None:
        def received(payload: str | bytes) -> None:
            if isinstance(payload, str):
                frames.append(json.loads(payload))

        socket.on("framereceived", received)

    page.on("websocket", watch)
    return frames


@given(
    parsers.parse('I open the "{path}" live page'),
    target_fixture="document_requests",
)
def open_live_page(
    page: Page,
    live_server: str,
    socket_frames: list[list[Any]],
    path: str,
) -> list[str]:
    del socket_frames  # Watch the socket before the page opens it.
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


@then(parsers.parse('"{selector}" is empty'))
def is_empty(page: Page, selector: str) -> None:
    expect(page.locator(selector)).to_have_text("")


@then(parsers.parse('"{selector}" shows the "{path}" URL'))
def shows_url(page: Page, live_server: str, selector: str, path: str) -> None:
    expect(page.locator(selector)).to_have_text(f"{live_server}{path}")


@then("the document was not reloaded")
def document_not_reloaded(
    document_requests: list[str], requests_before_click: int
) -> None:
    assert len(document_requests) == requests_before_click


@then("the document was reloaded")
def document_reloaded(document_requests: list[str], requests_before_click: int) -> None:
    assert len(document_requests) > requests_before_click


@then(parsers.parse('the "{name}" cookie is gone'))
def cookie_gone(page: Page, name: str) -> None:
    assert all(cookie.get("name") != name for cookie in page.context.cookies())


@when(
    parsers.parse('I visit "{path}" and it fails after connecting'),
    target_fixture="statuses",
)
def visit_failing_page(page: Page, live_server: str, path: str) -> list[int]:
    statuses: list[int] = []

    def record(response: Response) -> None:
        if response.request.is_navigation_request():
            statuses.append(response.status)

    page.on("response", record)
    with page.expect_response(
        lambda response: (
            response.request.is_navigation_request() and response.status == 404
        )
    ):
        page.goto(f"{live_server}{path}")
    # A looping client would request the document again within a few seconds.
    page.wait_for_timeout(1_000)
    return statuses


@then(parsers.parse("the document answered {first:d} and then {second:d}"))
def document_answered(statuses: list[int], first: int, second: int) -> None:
    assert statuses == [first, second]


_JOIN_FIELDS = {"_mounts", "_mount_attempts", "_track_static", "_live_referer"}


@when("the client reconnects", target_fixture="reconnect_url")
def reconnect(page: Page) -> str:
    with page.expect_websocket() as reconnected:
        page.evaluate("() => liveSocket.disconnect(() => liveSocket.connect())")
    expect(page.locator("[data-phx-main]")).to_have_class(
        re.compile(r"\bphx-connected\b")
    )
    return reconnected.value.url


@then(
    parsers.parse(
        'the reconnect URL carries "{name}={value}" and no LiveView join fields'
    )
)
def reconnect_url_fields(reconnect_url: str, name: str, value: str) -> None:
    query = parse_qsl(urlsplit(reconnect_url).query, keep_blank_values=True)
    assert (name, value) in query
    assert not {key.partition("[")[0] for key, _ in query} & _JOIN_FIELDS


def _latest_diff(frames: list[list[Any]]) -> dict[str, Any] | None:
    for frame in reversed(frames):
        if frame[3] == "diff":
            return frame[4]
        if frame[3] == "phx_reply" and "diff" in frame[4]["response"]:
            return frame[4]["response"]["diff"]
    return None


def _eventually(page: Page, check: Callable[[], bool]) -> None:
    # Frame events reach the sync API while it waits, so poll for a moment.
    for _ in range(40):
        if check():
            return
        page.wait_for_timeout(50)
    assert check()


@then(parsers.parse("the last update was {payload}"))
def last_update(page: Page, socket_frames: list[list[Any]], payload: str) -> None:
    expected = json.loads(payload)
    _eventually(page, lambda: _latest_diff(socket_frames) == expected)


@then(
    parsers.parse(
        "the last update gave component {cid:d} the statics of component {source:d}"
    )
)
def shared_statics(
    page: Page, socket_frames: list[list[Any]], cid: int, source: int
) -> None:
    def shared() -> bool:
        diff = _latest_diff(socket_frames) or {}
        component = diff.get("c", {}).get(str(cid), {})
        return component.get("s") == -source

    _eventually(page, shared)


@then(parsers.parse("the server destroyed component {cid:d}"))
def destroyed(page: Page, socket_frames: list[list[Any]], cid: int) -> None:
    def confirmed() -> bool:
        return any(
            frame[3] == "phx_reply" and cid in frame[4]["response"].get("cids", [])
            for frame in socket_frames
        )

    _eventually(page, confirmed)


@then(parsers.parse('the page title is "{title}"'))
def page_title(page: Page, title: str) -> None:
    expect(page).to_have_title(title)


@given(parsers.parse('I mark "{first}" and "{second}"'))
def mark(page: Page, first: str, second: str) -> None:
    for selector in (first, second):
        page.locator(selector).evaluate("node => node.setAttribute('data-mark', '')")


@then(parsers.parse('"{selector}" still has its mark'))
def still_marked(page: Page, selector: str) -> None:
    expect(page.locator(selector)).to_have_attribute("data-mark", "")


@then(parsers.parse('"{selector}" lost its mark'))
def mark_lost(page: Page, selector: str) -> None:
    expect(page.locator(selector)).not_to_have_attribute("data-mark", "")


@then(parsers.parse('"{selector}" is gone'))
def gone(page: Page, selector: str) -> None:
    expect(page.locator(selector)).to_have_count(0)


@then(parsers.parse('"{selector}" lists {count:d} items'))
def lists(page: Page, selector: str, count: int) -> None:
    expect(page.locator(f"{selector} > li")).to_have_count(count)
