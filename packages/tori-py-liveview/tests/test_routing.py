from __future__ import annotations

import asyncio
import json
import re
from typing import Any, cast

import httpx
import pytest
from starlette.types import ASGIApp, Message
from tori_py import NestApplication, module
from tori_py.starlette import StarletteAdapter
from tori_py_liveview import (
    LiveSession,
    LiveView,
    LiveViewConfigurationError,
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
    same_origin,
)


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
    assert not same_origin("testserver", "ftp://testserver/items")


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
            "diff": {"s": ["<output>2</output>"], "t": ""}
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
        assert cast(dict[str, object], replies[2][4])["response"] == {
            "diff": {"s": ["<output>callback</output>"], "t": ""}
        }
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
            "diff": {"s": ["<output>2</output>"], "t": ""}
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
