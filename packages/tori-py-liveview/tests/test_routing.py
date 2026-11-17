from __future__ import annotations

import asyncio
import json
import re
from typing import Any, cast
from urllib.parse import quote

import httpx
import pytest
from starlette.types import ASGIApp, Message
from tori_py import NestApplication, module
from tori_py.starlette import StarletteAdapter
from tori_py_liveview import (
    LiveSession,
    LiveView,
    LiveViewConfigurationError,
    LiveViewError,
    LiveViewModule,
    LiveViewOptions,
    MountContext,
    UnknownEventError,
    live_view,
)
from tori_py_liveview.routing import (
    LiveRoute,
    compile_live_routes,
    match_live_url,
    redirect_host_allowed,
    same_origin,
)
from tori_py_liveview.tokens import MountTokenCodec


@live_view("/articles/{article_id}/edit", action="edit")
class ArticleLive(LiveView):
    calls: list[tuple[str, object, object]] = []

    async def mount(self, context: MountContext) -> None:
        type(self).calls.append(("mount", dict(context.params), self.live_action))

    async def handle_params(self, params: dict[str, str], uri: str) -> None:
        type(self).calls.append(("params", dict(params), uri))

    def render(self):
        return "<article>edit</article>"


def test_live_view_accepts_action_and_stacked_routes() -> None:
    @live_view("/items", action="index")
    @live_view("/items/new", action="new")
    class ItemsLive(LiveView):
        def render(self):
            return "<div>items</div>"

    routes = ItemsLive.__dict__["__tori_py_liveview_routes__"]
    assert [(route.path, route.action) for route in routes] == [
        ("/items/new", "new"),
        ("/items", "index"),
    ]


def test_live_view_rejects_duplicate_paths_across_actions() -> None:
    @live_view("/items", action="index")
    class ItemsLive(LiveView):
        def render(self):
            return "<div>items</div>"

    @live_view("/items", action="show")
    class OtherLive(LiveView):
        def render(self):
            return "<div>other</div>"

    with pytest.raises(LiveViewConfigurationError, match="must be unique"):
        LiveViewModule.for_root(
            LiveViewOptions(secret="s" * 32),
            pages=[ItemsLive, OtherLive],
        )


def test_same_origin_accepts_relative_and_matching_urls_only() -> None:
    assert same_origin("testserver", "/items")
    assert same_origin("testserver", "http://testserver/items")
    assert same_origin("testserver", "http://testserver:80/items", scheme="http")
    assert not same_origin("testserver", "https://testserver/items", scheme="http")
    assert not same_origin("testserver", "http://other/items")
    assert not same_origin("testserver", "http://testserver:81/items")
    assert not same_origin("testserver", "//other/items")
    assert not same_origin("testserver", "///other/items")
    assert not same_origin("testserver", "ftp://testserver/items")


# Browsers read "\" as "/" here, so each of these leaves http://testserver/.
@pytest.mark.parametrize(
    "url",
    [
        "/\\evil.example",
        "\\\\evil.example",
        "\\/evil.example",
        "//\\evil.example",
        "/\\/evil.example",
    ],
)
def test_same_origin_reads_backslashes_like_browsers(url: str) -> None:
    assert not same_origin("testserver", url)
    assert not same_origin("testserver", url, scheme="http")


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/settings?tab=2#x", "/settings?tab=2#x"),
        ("settings", "settings"),
        (" /settings\n", "/settings"),
        ("/\\evil.example", "//evil.example"),
        ("https://idp.example/login", "https://idp.example/login"),
        ("/docs\\guide?q=C:\\Users#a\\b", "/docs/guide?q=C:\\Users#a\\b"),
        ("/docs#a\\b?c\\d", "/docs#a\\b?c\\d"),
    ],
)
def test_redirect_stores_the_cleaned_target(target: str, expected: str) -> None:
    page = ArticleLive()
    page.redirect(target)
    assert page._take_liveview_pending_redirect() == ("redirect", expected, "push")


@pytest.mark.parametrize(
    "target",
    [
        "javascript:alert(1)",
        " JaVaScRiPt:alert(1)",
        "java\nscript:alert(1)",
        "\x00javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "ftp://testserver/file",
        "https:evil.example",
        "//",
        " \t",
    ],
)
def test_redirect_rejects_targets_other_than_paths_and_http_urls(
    target: str,
) -> None:
    page = ArticleLive()
    with pytest.raises(LiveViewError, match="path or an http"):
        page.redirect(target)
    assert page._take_liveview_pending_redirect() is None


@pytest.mark.parametrize(
    ("target", "allowed"),
    [
        ("/settings", True),
        ("settings", True),
        ("https://testserver/settings", True),
        ("http://TestServer:8080/settings", True),
        ("https://idp.example/login", True),
        ("https://IdP.Example/login", True),
        ("//evil.example", False),
        ("https://evil.example/", False),
        ("https://testserver@evil.example/", False),
    ],
)
def test_redirect_host_allowed_compares_host_names(target: str, allowed: bool) -> None:
    assert redirect_host_allowed("testserver", target, ("idp.example",)) is allowed


def test_route_matching_preserves_unicode_query_values() -> None:
    routes = compile_live_routes((LiveRoute("/search", None, "SearchLive"),))

    resolved = match_live_url(routes, "/search?q=caf%C3%A9")

    assert resolved is not None
    assert resolved[1] == {"q": "café"}


def test_route_matching_keeps_path_parameters_over_query_parameters() -> None:
    routes = compile_live_routes(
        (LiveRoute("/articles/{article_id}", None, "ArticleLive"),)
    )

    resolved = match_live_url(routes, "/articles/42?article_id=99")

    assert resolved is not None
    assert resolved[1] == {"article_id": "42"}


def _asgi(application: NestApplication) -> ASGIApp:
    return application.get_adapter(StarletteAdapter).app


async def _request(application: NestApplication, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=_asgi(application))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        return await client.get(path)


def _websocket_scope(path: str) -> Any:
    return {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.5"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"host", b"testserver"), (b"origin", b"http://testserver")],
        "client": ("test", 1),
        "server": ("testserver", 80),
        "subprotocols": [],
    }


async def _call_websocket(
    application: NestApplication, path: str, *incoming: Message
) -> list[Message]:
    messages: asyncio.Queue[Message] = asyncio.Queue()
    await messages.put({"type": "websocket.connect"})
    for message in incoming:
        await messages.put(message)
    sent: list[Message] = []

    async def receive() -> Message:
        return await messages.get()

    async def send(message: Message) -> None:
        sent.append(message)

    await _asgi(application)(_websocket_scope(path), receive, send)
    return sent


def _receive_text(payload: object) -> Message:
    return {"type": "websocket.receive", "text": json.dumps(payload)}


def _token(document: str) -> str:
    match = re.search(r'data-phx-session="([A-Za-z0-9_.-]+)"', document)
    assert match is not None
    return match[1]


@pytest.mark.asyncio
async def test_http_mount_runs_handle_params_with_merged_params() -> None:
    ArticleLive.calls.clear()
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32), pages=[ArticleLive]
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    try:
        page = await _request(application, "/articles/42/edit?tab=info")
        assert page.status_code == 200
        assert ArticleLive.calls[0] == ("mount", {"article_id": "42"}, "edit")
        kind, params, uri = ArticleLive.calls[1]
        assert kind == "params"
        assert cast(dict[str, str], params)["article_id"] == "42"
        assert cast(dict[str, str], params)["tab"] == "info"
        assert cast(str, uri).endswith("/articles/42/edit?tab=info")
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_http_mount_selects_the_stacked_route_action() -> None:
    @live_view("/stacked", action="index")
    @live_view("/stacked/new", action="new")
    class StackedLive(LiveView):
        def render(self):
            return f"<article>{self.live_action}</article>"

    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32), pages=[StackedLive]
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    try:
        page = await _request(application, "/stacked/new")
        assert page.status_code == 200
        assert "<article>new</article>" in page.text
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_http_mount_redirect_returns_302() -> None:
    @live_view("/mount-redirect")
    class MountRedirectLive(LiveView):
        async def mount(self, context: MountContext) -> None:
            del context
            self.redirect("/other")

        def render(self):
            return "<div>never rendered</div>"

    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32), pages=[MountRedirectLive, OtherLive]
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    try:
        response = await _request(application, "/mount-redirect")
        assert response.status_code == 302
        assert response.headers["location"] == "/other"
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_http_mount_redirect_keeps_untrusted_next_on_allowed_hosts() -> None:
    @live_view("/mount-next")
    class MountNextLive(LiveView):
        async def mount(self, context: MountContext) -> None:
            self.redirect(context.query_params["next"])

        def render(self):
            return "<div>never rendered</div>"

    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32, redirect_hosts=("idp.example",)),
        pages=[MountNextLive],
        key="mount-next",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    try:
        for target, location in (
            ("/settings?tab=2", "/settings?tab=2"),
            ("https://testserver/settings", "https://testserver/settings"),
            ("https://idp.example/login", "https://idp.example/login"),
        ):
            response = await _request(
                application, f"/mount-next?next={quote(target, safe='')}"
            )
            assert response.status_code == 302
            assert response.headers["location"] == location
        for target in ("/\\evil.example", "https://evil.example/", "javascript:x"):
            response = await _request(
                application, f"/mount-next?next={quote(target, safe='')}"
            )
            assert response.status_code == 500
            assert "location" not in response.headers
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_http_mount_navigation_never_leaves_the_request_host() -> None:
    @live_view("/mount-navigate")
    class MountNavigateLive(LiveView):
        async def mount(self, context: MountContext) -> None:
            self.push_navigate(context.query_params["next"])

        def render(self):
            return "<div>never rendered</div>"

    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[MountNavigateLive],
        key="mount-navigate",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    try:
        response = await _request(application, "/mount-navigate?next=%2Fsettings")
        assert response.status_code == 302
        assert response.headers["location"] == "/settings"
        for target in ("///evil.example", "//\\evil.example", "/\\/evil.example"):
            response = await _request(
                application, f"/mount-navigate?next={quote(target, safe='')}"
            )
            assert response.status_code == 500
            assert "location" not in response.headers
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_websocket_join_runs_handle_params_for_join_url() -> None:
    ArticleLive.calls.clear()
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32), pages=[ArticleLive]
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    try:
        page = await _request(application, "/articles/42/edit?tab=info")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _receive_text(
                [
                    "1",
                    "1",
                    "lv:tori-live-root",
                    "phx_join",
                    {
                        "url": "http://testserver/articles/42/edit?tab=info",
                        "params": {"_mounts": 0, "_mount_attempts": 0},
                        "session": token,
                        "static": None,
                        "sticky": False,
                    },
                ]
            ),
            {"type": "websocket.disconnect", "code": 1000, "reason": ""},
        )
        replies = [
            json.loads(cast(str, message["text"]))
            for message in sent
            if message["type"] == "websocket.send"
        ]
        assert replies[0][3] == "phx_reply"
        assert replies[0][4]["status"] == "ok"
        kinds = [call[0] for call in ArticleLive.calls]
        assert kinds == ["mount", "params", "mount", "params"]
        assert ArticleLive.calls[3][0] == "params"
        assert cast(dict[str, str], ArticleLive.calls[3][1])["article_id"] == "42"
    finally:
        await application.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "join_url",
    [
        "http://testserver/articles/43/edit?tab=info",
        "http://testserver/articles/42/edit?tab=other",
    ],
)
async def test_websocket_join_rejects_url_different_from_mount_token(
    join_url: str,
) -> None:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32), pages=[ArticleLive], key="signed-url"
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    try:
        page = await _request(application, "/articles/42/edit?tab=info")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, join_url),
        )
        replies = _replies(sent)
        assert cast(dict[str, object], replies[0][4]) == {
            "status": "error",
            "response": {"reason": "unauthorized"},
        }
    finally:
        await application.shutdown()


@live_view("/pages", action="index")
class PagesLive(LiveView):
    params_calls: list[dict[str, str]] = []
    page_number = "1"

    async def handle_params(self, params: dict[str, str], uri: str) -> None:
        del uri
        type(self).params_calls.append(dict(params))
        self.page_number = params.get("page", "1")

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event == "go":
            self.push_patch("/pages?page=2")
        elif event == "external-patch":
            self.push_patch("https://evil.example/pages?page=2")
        elif event == "external-navigate":
            self.push_navigate("https://evil.example/other")
        else:
            raise UnknownEventError(event)

    def render(self):
        return f"<output>{self.page_number}</output>"


@live_view("/other")
class OtherLive(LiveView):
    def render(self):
        return "<div>other</div>"


def _join_pages(token: str, url: str, *, ref: str = "1") -> Message:
    return _receive_text(
        [
            ref,
            ref,
            "lv:tori-live-root",
            "phx_join",
            {
                "url": url,
                "params": {"_mounts": 0, "_mount_attempts": 0},
                "session": token,
                "static": None,
                "sticky": False,
            },
        ]
    )


def _live_patch(url: str, *, ref: str = "2") -> Message:
    return _receive_text(["1", ref, "lv:tori-live-root", "live_patch", {"url": url}])


def _join_redirect(token: str, target: str, *, ref: str = "1") -> Message:
    return _receive_text(
        [
            ref,
            ref,
            "lv:tori-live-root",
            "phx_join",
            {
                "redirect": target,
                "params": {"_mounts": 0, "_mount_attempts": 0},
                "session": token,
                "static": None,
                "sticky": False,
            },
        ]
    )


def _replies(sent: list[Message]) -> list[list[object]]:
    return [
        cast(list[object], json.loads(cast(str, message["text"])))
        for message in sent
        if message["type"] == "websocket.send"
    ]


async def _pages_application() -> NestApplication:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[PagesLive, OtherLive],
        key="paging",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    return application


@pytest.mark.asyncio
async def test_live_patch_event_runs_handle_params_and_replies_diff() -> None:
    PagesLive.params_calls.clear()
    application = await _pages_application()
    try:
        page = await _request(application, "/pages")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/pages"),
            _live_patch("http://testserver/pages?page=2"),
            {"type": "websocket.disconnect", "code": 1000, "reason": ""},
        )
        replies = _replies(sent)
        assert replies[0][3] == "phx_reply"
        assert cast(dict[str, object], replies[0][4])["status"] == "ok"
        assert replies[1][3] == "phx_reply"
        assert cast(dict[str, object], replies[1][4])["status"] == "ok"
        assert cast(dict[str, object], replies[1][4])["response"] == {
            "diff": {"s": ["<output>2</output>"]}
        }
        assert PagesLive.params_calls[-1] == {"page": "2"}
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_live_patch_drains_navigation_queued_by_handle_params() -> None:
    params_calls: list[dict[str, str]] = []

    @live_view("/callback-patch")
    class CallbackPatchLive(LiveView):
        async def handle_params(self, params: dict[str, str], uri: str) -> None:
            del uri
            params_calls.append(dict(params))
            if params.get("step") == "2":
                self.push_patch("/callback-patch?step=3")

        def render(self):
            return "<output>callback</output>"

    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32), pages=[CallbackPatchLive], key="callback"
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    try:
        page = await _request(application, "/callback-patch")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/callback-patch"),
            _live_patch("http://testserver/callback-patch?step=2"),
            {"type": "websocket.disconnect", "code": 1000, "reason": ""},
        )
        replies = _replies(sent)
        assert replies[1] == [
            "1",
            None,
            "lv:tori-live-root",
            "live_patch",
            {"kind": "push", "to": "/callback-patch?step=3"},
        ]
        # The page renders the same constant output, so the patch changes nothing.
        assert cast(dict[str, object], replies[2][4])["response"] == {"diff": {}}
        assert params_calls[-2:] == [{"step": "2"}, {"step": "3"}]
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_live_patch_to_another_view_replies_link_redirect() -> None:
    PagesLive.params_calls.clear()
    application = await _pages_application()
    try:
        page = await _request(application, "/pages")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/pages"),
            _live_patch("http://testserver/other"),
            {"type": "websocket.disconnect", "code": 1000, "reason": ""},
        )
        replies = _replies(sent)
        assert cast(dict[str, object], replies[1][4]) == {
            "status": "ok",
            "response": {"link_redirect": True},
        }
        assert PagesLive.params_calls == [{}, {}]
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_push_patch_from_event_sends_diff_and_live_patch_push() -> None:
    PagesLive.params_calls.clear()
    application = await _pages_application()
    try:
        page = await _request(application, "/pages")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/pages"),
            _receive_text(
                [
                    "1",
                    "2",
                    "lv:tori-live-root",
                    "event",
                    {"type": "click", "event": "go", "value": None},
                ]
            ),
            {"type": "websocket.disconnect", "code": 1000, "reason": ""},
        )
        replies = _replies(sent)
        assert replies[1] == [
            "1",
            None,
            "lv:tori-live-root",
            "live_patch",
            {"kind": "push", "to": "/pages?page=2"},
        ]
        assert cast(dict[str, object], replies[2][4])["status"] == "ok"
        assert cast(dict[str, object], replies[2][4])["response"] == {
            "diff": {"s": ["<output>2</output>"]}
        }
        assert PagesLive.params_calls[-1] == {"page": "2"}
    finally:
        await application.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["external-patch", "external-navigate"])
async def test_server_navigation_rejects_cross_origin_targets(event: str) -> None:
    application = await _pages_application()
    try:
        page = await _request(application, "/pages")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/pages"),
            _receive_text(
                [
                    "1",
                    "2",
                    "lv:tori-live-root",
                    "event",
                    {"type": "click", "event": event, "value": None},
                ]
            ),
        )
        assert sent[-1]["type"] == "websocket.close"
        assert sent[-1]["code"] == 1011
        assert not any(
            message.get("type") == "websocket.send"
            and "live_redirect" in cast(str, message.get("text", ""))
            for message in sent
        )
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_same_page_push_navigate_uses_live_redirect() -> None:
    @live_view("/same-page", action="index")
    @live_view("/same-page/edit", action="edit")
    class SamePageLive(LiveView):
        async def handle_event(self, event: str, value: object) -> None:
            del value
            if event != "edit":
                raise UnknownEventError(event)
            self.push_navigate("/same-page/edit")

        def render(self):
            return "<div>same page</div>"

    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32), pages=[SamePageLive], key="same-page"
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    try:
        page = await _request(application, "/same-page")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/same-page"),
            _receive_text(
                [
                    "1",
                    "2",
                    "lv:tori-live-root",
                    "event",
                    {"type": "click", "event": "edit", "value": None},
                ]
            ),
            # Otherwise the server waits for the next join until its idle deadline.
            {"type": "websocket.disconnect", "code": 1000, "reason": ""},
        )
        replies = _replies(sent)
        assert cast(dict[str, object], replies[1][4]) == {
            "status": "ok",
            "response": {"live_redirect": {"kind": "push", "to": "/same-page/edit"}},
        }
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_join_with_stale_stacked_action_is_unauthorized() -> None:
    @live_view("/stale-action", action="index")
    @live_view("/stale-action/edit", action="edit")
    class StaleActionLive(LiveView):
        def render(self):
            return "<div>stale action</div>"

    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32), pages=[StaleActionLive], key="stale-action"
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    try:
        page = await _request(application, "/stale-action")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/stale-action/edit"),
        )
        replies = _replies(sent)
        assert cast(dict[str, object], replies[0][4]) == {
            "status": "error",
            "response": {"reason": "unauthorized"},
        }
    finally:
        await application.shutdown()


session_calls: list[tuple[str, bool]] = []


async def stamp_team(page: LiveView, context: MountContext) -> None:
    session_calls.append((type(page).__name__, context.connected))


@live_view("/team-users", session="team")
class TeamUsersLive(LiveView):
    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event == "go-settings":
            self.push_navigate("/team-settings")
        elif event == "go-admin":
            self.push_navigate("/admin")
        elif event == "go-away":
            self.redirect("/other")
        elif event == "go-evil":
            self.redirect("/\\evil.example")
        else:
            raise UnknownEventError(event)

    def render(self):
        return "<div>users</div>"


@live_view("/team-settings", session="team")
class TeamSettingsLive(LiveView):
    joined_params: list[dict[str, str]] = []

    async def handle_params(self, params: dict[str, str], uri: str) -> None:
        del uri
        type(self).joined_params.append(dict(params))

    def render(self):
        return "<div>settings</div>"


@live_view("/admin", session="admin")
class AdminLive(LiveView):
    def render(self):
        return "<div>admin</div>"


async def _session_application() -> NestApplication:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[TeamUsersLive, TeamSettingsLive, AdminLive],
        sessions=[
            LiveSession("team", on_mount=(stamp_team,)),
            LiveSession("admin"),
        ],
        key="sessions",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    return application


def test_live_session_rejects_unknown_and_duplicate_sessions() -> None:
    @live_view("/nope", session="missing")
    class NopeLive(LiveView):
        def render(self):
            return "<div>nope</div>"

    with pytest.raises(LiveViewConfigurationError, match="unknown session"):
        LiveViewModule.for_root(LiveViewOptions(secret="s" * 32), pages=[NopeLive])
    with pytest.raises(LiveViewConfigurationError, match="unique"):
        LiveViewModule.for_root(
            LiveViewOptions(secret="s" * 32),
            pages=[AdminLive],
            sessions=[LiveSession("admin"), LiveSession("admin")],
        )


@pytest.mark.asyncio
async def test_on_mount_runs_before_mount_on_http_and_join() -> None:
    session_calls.clear()
    application = await _session_application()
    try:
        page = await _request(application, "/team-users")
        assert page.status_code == 200
        assert session_calls == [("TeamUsersLive", False)]
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/team-users"),
            {"type": "websocket.disconnect", "code": 1000, "reason": ""},
        )
        assert cast(dict[str, object], _replies(sent)[0][4])["status"] == "ok"
        assert session_calls == [
            ("TeamUsersLive", False),
            ("TeamUsersLive", True),
        ]
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_push_navigate_rejoins_new_page_in_session() -> None:
    session_calls.clear()
    TeamSettingsLive.joined_params.clear()
    application = await _session_application()
    try:
        page = await _request(application, "/team-users")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/team-users"),
            _receive_text(
                [
                    "1",
                    "2",
                    "lv:tori-live-root",
                    "event",
                    {"type": "click", "event": "go-settings", "value": None},
                ]
            ),
            _receive_text(
                [
                    "1",
                    "1",
                    "lv:tori-live-root",
                    "phx_join",
                    {
                        "redirect": "http://testserver/team-settings",
                        "params": {"_mounts": 0, "_mount_attempts": 0},
                        "session": token,
                        "static": None,
                        "sticky": False,
                    },
                ]
            ),
            {"type": "websocket.disconnect", "code": 1000, "reason": ""},
        )
        replies = _replies(sent)
        assert cast(dict[str, object], replies[1][4]) == {
            "status": "ok",
            "response": {"live_redirect": {"kind": "push", "to": "/team-settings"}},
        }
        assert cast(dict[str, object], replies[2][4])["status"] == "ok"
        assert TeamSettingsLive.joined_params == [{}]
        assert ("TeamSettingsLive", True) in session_calls
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_push_navigate_back_to_a_page_creates_a_fresh_instance() -> None:
    class_a_instances: list[object] = []

    @live_view("/page-a", session="cycle")
    class PageALive(LiveView):
        async def mount(self, context: MountContext) -> None:
            if context.connected:
                class_a_instances.append(self)

        async def handle_event(self, event: str, value: object) -> None:
            del value
            if event != "next":
                raise UnknownEventError(event)
            self.push_navigate("/page-b")

        def render(self):
            return "<div>a</div>"

    @live_view("/page-b", session="cycle")
    class PageBLive(LiveView):
        async def handle_event(self, event: str, value: object) -> None:
            del value
            if event != "back":
                raise UnknownEventError(event)
            self.push_navigate("/page-a")

        def render(self):
            return "<div>b</div>"

    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[PageALive, PageBLive],
        sessions=[LiveSession("cycle")],
        key="fresh-page",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    try:
        page = await _request(application, "/page-a")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/page-a"),
            _receive_text(
                [
                    "1",
                    "2",
                    "lv:tori-live-root",
                    "event",
                    {"type": "click", "event": "next", "value": None},
                ]
            ),
            _join_redirect(token, "http://testserver/page-b"),
            _receive_text(
                [
                    "1",
                    "3",
                    "lv:tori-live-root",
                    "event",
                    {"type": "click", "event": "back", "value": None},
                ]
            ),
            _join_redirect(token, "http://testserver/page-a"),
            {"type": "websocket.disconnect", "code": 1000, "reason": ""},
        )
        replies = _replies(sent)
        assert cast(dict[str, object], replies[1][4])["response"] == {
            "live_redirect": {"kind": "push", "to": "/page-b"}
        }
        assert cast(dict[str, object], replies[3][4])["response"] == {
            "live_redirect": {"kind": "push", "to": "/page-a"}
        }
        assert len(class_a_instances) == 2
        assert class_a_instances[0] is not class_a_instances[1]
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_push_navigate_across_sessions_replies_redirect() -> None:
    application = await _session_application()
    try:
        page = await _request(application, "/team-users")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/team-users"),
            _receive_text(
                [
                    "1",
                    "2",
                    "lv:tori-live-root",
                    "event",
                    {"type": "click", "event": "go-admin", "value": None},
                ]
            ),
        )
        replies = _replies(sent)
        assert cast(dict[str, object], replies[1][4]) == {
            "status": "ok",
            "response": {"redirect": {"to": "/admin"}},
        }
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_redirect_from_event_replies_redirect() -> None:
    application = await _session_application()
    try:
        page = await _request(application, "/team-users")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/team-users"),
            _receive_text(
                [
                    "1",
                    "2",
                    "lv:tori-live-root",
                    "event",
                    {"type": "click", "event": "go-away", "value": None},
                ]
            ),
        )
        replies = _replies(sent)
        assert cast(dict[str, object], replies[1][4]) == {
            "status": "ok",
            "response": {"redirect": {"to": "/other"}},
        }
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_redirect_to_another_host_from_event_is_never_sent() -> None:
    application = await _session_application()
    try:
        page = await _request(application, "/team-users")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/team-users"),
            _receive_text(
                [
                    "1",
                    "2",
                    "lv:tori-live-root",
                    "event",
                    {"type": "click", "event": "go-evil", "value": None},
                ]
            ),
        )
        assert all("evil.example" not in str(message) for message in sent)
        assert sent[-1]["type"] == "websocket.close"
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_navigate_join_across_sessions_is_unauthorized() -> None:
    application = await _session_application()
    try:
        page = await _request(application, "/team-users")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _receive_text(
                [
                    "1",
                    "1",
                    "lv:tori-live-root",
                    "phx_join",
                    {
                        "redirect": "http://testserver/admin",
                        "params": {"_mounts": 0, "_mount_attempts": 0},
                        "session": token,
                        "static": None,
                        "sticky": False,
                    },
                ]
            ),
        )
        replies = _replies(sent)
        assert cast(dict[str, object], replies[0][4]) == {
            "status": "error",
            "response": {"reason": "unauthorized"},
        }
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_push_patch_to_another_view_closes_with_1011() -> None:
    @live_view("/stale-push")
    class StalePushLive(LiveView):
        async def handle_event(self, event: str, value: object) -> None:
            del event, value
            self.push_patch("/other")

        def render(self):
            return "<div>stale</div>"

    stale_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[StalePushLive, OtherLive],
        key="stale-push",
    )

    @module(imports=[stale_module])
    class StaleRoot:
        pass

    stale_application = await NestApplication.create(
        StaleRoot, adapter=StarletteAdapter()
    )
    await stale_application.start()
    try:
        stale_page = await _request(stale_application, "/stale-push")
        stale_token = _token(stale_page.text)
        sent = await _call_websocket(
            stale_application,
            "/_tori/live/websocket",
            _join_pages(stale_token, "http://testserver/stale-push"),
            _receive_text(
                [
                    "1",
                    "2",
                    "lv:tori-live-root",
                    "event",
                    {"type": "click", "event": "go", "value": None},
                ]
            ),
        )
        assert sent[-1]["type"] == "websocket.close"
        assert sent[-1]["code"] == 1011
    finally:
        await stale_application.shutdown()


@pytest.mark.asyncio
async def test_push_patch_cannot_cross_session_on_one_page_class() -> None:
    @live_view("/shared-team", session="team")
    @live_view("/shared-admin", session="admin")
    class SharedLive(LiveView):
        async def handle_event(self, event: str, value: object) -> None:
            del value
            if event != "bad-patch":
                raise UnknownEventError(event)
            self.push_patch("/shared-admin")

        def render(self):
            return "<div>shared</div>"

    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[SharedLive],
        sessions=[LiveSession("team"), LiveSession("admin")],
        key="shared-session",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    try:
        page = await _request(application, "/shared-team")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/shared-team"),
            _receive_text(
                [
                    "1",
                    "2",
                    "lv:tori-live-root",
                    "event",
                    {"type": "click", "event": "bad-patch", "value": None},
                ]
            ),
        )
        assert sent[-1]["type"] == "websocket.close"
        assert sent[-1]["code"] == 1011
    finally:
        await application.shutdown()


@live_view("/info-nav", session="team")
class InfoNavLive(LiveView):
    async def mount(self, context: MountContext) -> None:
        if context.connected:
            self.send_info("go")

    async def handle_info(self, name: str, value: object) -> None:
        del name, value
        self.push_navigate("/team-settings")

    def render(self):
        return "<div>infonav</div>"


@pytest.mark.asyncio
async def test_push_navigate_from_info_rejoins_new_page() -> None:
    TeamSettingsLive.joined_params.clear()
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[InfoNavLive, TeamSettingsLive],
        sessions=[LiveSession("team")],
        key="info-navigate",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    try:
        page = await _request(application, "/info-nav")
        token = _token(page.text)
        incoming: asyncio.Queue[Message] = asyncio.Queue()
        await incoming.put({"type": "websocket.connect"})
        await incoming.put(_join_pages(token, "http://testserver/info-nav"))
        sent: list[Message] = []
        rejoined = False

        async def receive() -> Message:
            return await incoming.get()

        async def send(message: Message) -> None:
            nonlocal rejoined
            sent.append(message)
            if (
                not rejoined
                and message["type"] == "websocket.send"
                and '"live_redirect"' in cast(str, message.get("text", ""))
            ):
                rejoined = True
                await incoming.put(
                    _receive_text(
                        [
                            "1",
                            "1",
                            "lv:tori-live-root",
                            "phx_join",
                            {
                                "redirect": "http://testserver/team-settings",
                                "params": {"_mounts": 0, "_mount_attempts": 0},
                                "session": token,
                                "static": None,
                                "sticky": False,
                            },
                        ]
                    )
                )
                await incoming.put(
                    {"type": "websocket.disconnect", "code": 1000, "reason": ""}
                )

        await _asgi(application)(
            _websocket_scope("/_tori/live/websocket"), receive, send
        )
        replies = _replies(sent)
        assert replies[1] == [
            "1",
            None,
            "lv:tori-live-root",
            "live_redirect",
            {"kind": "push", "to": "/team-settings"},
        ]
        assert cast(dict[str, object], replies[2][4])["status"] == "ok"
        assert TeamSettingsLive.joined_params == [{}]
    finally:
        await application.shutdown()


# ------------------------------------------------------- Document keys


async def _document_application(
    *pages: type[LiveView],
) -> NestApplication:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=list(pages),
        key="documents",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    return application


def _document_pages(
    disconnects: list[str] | None = None,
) -> tuple[type[LiveView], ...]:
    @live_view("/plain-a")
    class PlainALive(LiveView):
        def render(self):
            return "<div>plain a</div>"

    @live_view("/plain-b")
    class PlainBLive(LiveView):
        def render(self):
            return "<div>plain b</div>"

    @live_view("/blue-a")
    class BlueALive(LiveView):
        def document_key(self) -> str | None:
            return "blue"

        def render(self):
            return "<div>blue a</div>"

    @live_view("/blue-b")
    class BlueBLive(LiveView):
        def document_key(self) -> str | None:
            return "blue"

        def render(self):
            return "<div>blue b</div>"

    @live_view("/green")
    class GreenLive(LiveView):
        def document_key(self) -> str | None:
            return "green"

        async def disconnect(self) -> None:
            if disconnects is not None:
                disconnects.append("green")

        def render(self):
            return "<div>green</div>"

    return PlainALive, PlainBLive, BlueALive, BlueBLive, GreenLive


async def _navigate(
    application: NestApplication, start: str, target: str
) -> dict[str, object]:
    """Join ``start``, leave it, and join ``target`` as live navigation does.

    Returns the reply to the join of ``target``.
    """
    page = await _request(application, start)
    token = _token(page.text)
    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join_pages(token, f"http://testserver{start}"),
        _receive_text(["1", "2", "lv:tori-live-root", "phx_leave", {}]),
        _join_redirect(token, f"http://testserver{target}", ref="3"),
        {"type": "websocket.disconnect", "code": 1000, "reason": ""},
    )
    return cast(dict[str, object], _replies(sent)[-1][4])


@pytest.mark.asyncio
async def test_the_mount_token_carries_the_digest_of_the_document_key() -> None:
    application = await _document_application(*_document_pages())
    try:
        blue = _token((await _request(application, "/blue-a")).text)
        plain = _token((await _request(application, "/plain-a")).text)
        codec = MountTokenCodec("s" * 32)

        assert codec.verify(plain).document is None
        digest = codec.verify(blue).document
        assert digest is not None
        assert len(digest) == 32
        assert (
            digest
            == codec.verify(
                _token((await _request(application, "/blue-b")).text)
            ).document
        )
        assert (
            digest
            != codec.verify(
                _token((await _request(application, "/green")).text)
            ).document
        )
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_pages_without_a_document_key_navigate_as_before() -> None:
    application = await _document_application(*_document_pages())
    try:
        reply = await _navigate(application, "/plain-a", "/plain-b")

        assert reply["status"] == "ok"
        assert "rendered" in cast(dict[str, object], reply["response"])
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_pages_with_the_same_document_key_share_a_document() -> None:
    application = await _document_application(*_document_pages())
    try:
        reply = await _navigate(application, "/blue-a", "/blue-b?x=1")

        assert reply["status"] == "ok"
        assert "rendered" in cast(dict[str, object], reply["response"])
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_a_page_with_another_document_key_loads_a_new_document() -> None:
    disconnects: list[str] = []
    application = await _document_application(*_document_pages(disconnects))
    try:
        reply = await _navigate(application, "/blue-a", "/green?tab=two")

        assert reply == {
            "status": "error",
            "response": {"redirect": {"to": "/green?tab=two"}},
        }
        # The page mounted, so it is disconnected once, and it never rendered.
        assert disconnects == ["green"]
    finally:
        await application.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "target"), [("/plain-a", "/blue-a"), ("/blue-a", "/plain-a")]
)
async def test_a_keyed_and_an_unkeyed_page_do_not_share_a_document(
    start: str, target: str
) -> None:
    application = await _document_application(*_document_pages())
    try:
        reply = await _navigate(application, start, target)

        assert reply == {
            "status": "error",
            "response": {"redirect": {"to": target}},
        }
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_the_key_is_read_after_mount_and_handle_params() -> None:
    @live_view("/start")
    class StartLive(LiveView):
        def document_key(self) -> str | None:
            return "mine"

        def render(self):
            return "<div>start</div>"

    @live_view("/look")
    class LookLive(LiveView):
        def __init__(self) -> None:
            self.look = "unset"

        async def mount(self, context: MountContext) -> None:
            if context.connected:
                self.look = context.query_params.get("look", "unset")

        async def handle_params(self, params: dict[str, str], uri: str) -> None:
            del params
            if "tab=" in uri:
                self.look = "mine"

        def document_key(self) -> str | None:
            return "mine" if self.look == "mine" else "other"

        def render(self):
            return "<div>look</div>"

    application = await _document_application(StartLive, LookLive)
    try:
        same = await _navigate(application, "/start", "/look?look=mine")
        other = await _navigate(application, "/start", "/look?look=other")
        params = await _navigate(application, "/start", "/look?tab=1")

        assert same["status"] == "ok"
        assert other == {
            "status": "error",
            "response": {"redirect": {"to": "/look?look=other"}},
        }
        assert params["status"] == "ok"
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_a_navigation_the_page_queued_gives_way_to_its_own_document() -> None:
    @live_view("/start")
    class StartLive(LiveView):
        def render(self):
            return "<div>start</div>"

    @live_view("/moving")
    class MovingLive(LiveView):
        async def mount(self, context: MountContext) -> None:
            if context.connected:
                self.push_navigate("/start")

        def document_key(self) -> str | None:
            return "moving"

        def render(self):
            return "<div>moving</div>"

    application = await _document_application(StartLive, MovingLive)
    try:
        reply = await _navigate(application, "/start", "/moving")

        # The page is not displayed in this document, so its own navigation
        # runs in the new one.
        assert reply == {
            "status": "error",
            "response": {"redirect": {"to": "/moving"}},
        }
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_a_first_join_and_a_reconnect_never_compare_keys() -> None:
    @live_view("/drifting")
    class DriftingLive(LiveView):
        calls = 0

        def document_key(self) -> str | None:
            type(self).calls += 1
            return str(type(self).calls)

        def render(self):
            return "<div>drifting</div>"

    application = await _document_application(DriftingLive)
    try:
        page = await _request(application, "/drifting")
        token = _token(page.text)
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/drifting"),
            {"type": "websocket.disconnect", "code": 1000, "reason": ""},
        )
        again = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_pages(token, "http://testserver/drifting"),
            {"type": "websocket.disconnect", "code": 1000, "reason": ""},
        )

        # The key changed after the HTTP render, so a comparison would have
        # reloaded, and the reloaded page would have reloaded again.
        assert cast(dict[str, object], _replies(sent)[0][4])["status"] == "ok"
        assert cast(dict[str, object], _replies(again)[0][4])["status"] == "ok"
    finally:
        await application.shutdown()


@pytest.mark.asyncio
async def test_the_flash_follows_a_navigation_to_another_document() -> None:
    @live_view("/start")
    class StartLive(LiveView):
        def render(self):
            return "<div>start</div>"

    @live_view("/other-document")
    class OtherDocumentLive(LiveView):
        async def mount(self, context: MountContext) -> None:
            if context.connected:
                self.put_flash("info", "Moved")

        def document_key(self) -> str | None:
            return "other"

        def render(self):
            return "<div>other</div>"

    application = await _document_application(StartLive, OtherDocumentLive)
    try:
        reply = await _navigate(application, "/start", "/other-document")

        response = cast(dict[str, object], reply["response"])
        redirect = cast(dict[str, object], response["redirect"])
        assert redirect["to"] == "/other-document"
        # The flash the page put travels with the full page load.
        assert "flash" in redirect
    finally:
        await application.shutdown()


def test_a_document_key_must_be_a_string_or_none() -> None:
    class Numbered(LiveView):
        def document_key(self) -> str | None:
            return 5  # ty: ignore[invalid-return-type]

        def render(self):
            return ""

    class Named(LiveView):
        def document_key(self) -> str | None:
            return ""

        def render(self):
            return ""

    with pytest.raises(
        LiveViewError, match="document_key must return a string or None"
    ):
        Numbered()._document_digest()
    # An empty key is a key, not the absence of one.
    assert Named()._document_digest() is not None
    assert Named()._document_digest() != _Plain()._document_digest()


class _Plain(LiveView):
    def render(self):
        return ""
