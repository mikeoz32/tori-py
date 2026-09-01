from __future__ import annotations

import asyncio
import hashlib
import json
import re
from importlib.resources import files
from typing import Any, cast

import httpx
import pytest
from starlette.datastructures import QueryParams
from starlette.types import ASGIApp, Message
from tori_py import (
    ClassProvider,
    ModuleSpec,
    NestApplication,
    Scope,
    get_controller_metadata,
    get_route_metadata,
    get_websocket_gateway_metadata,
    module,
)
from tori_py.starlette import StarletteAdapter
from tori_py_liveview import (
    LiveComponent,
    LiveView,
    LiveViewConfigurationError,
    LiveViewError,
    LiveViewModule,
    LiveViewOptions,
    MountContext,
    UnknownEventError,
    live_view,
    rendered,
)


@live_view("/counter")
class CounterLive(LiveView):
    mounts: list[bool] = []
    disconnects = 0

    def __init__(self) -> None:
        self.count = 0

    async def mount(self, context: MountContext) -> None:
        type(self).mounts.append(context.connected)
        self.count = int(context.query_params.get("start", "0"))

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "increment":
            raise UnknownEventError(event)
        self.count += 1

    def render(self):
        return (
            t'<section><button phx-click="increment">+</button>'
            t"<output>{self.count}</output></section>"
        )

    def title(self) -> str:
        return f"Counter {self.count}"

    async def disconnect(self) -> None:
        type(self).disconnects += 1


@live_view("/untitled")
class UntitledLive(LiveView):
    def render(self) -> str:
        return "<p>Untitled</p>"


@live_view("/crash")
class CrashingLive(LiveView):
    def render(self) -> str:
        return "<p>Ready</p>"

    async def handle_event(self, event: str, value: object) -> None:
        del event, value
        raise RuntimeError("handler failed")


class CrashingComponent(LiveComponent):
    disconnects = 0

    async def handle_event(self, event: str, value: object) -> None:
        del event, value
        raise RuntimeError("component handler failed")

    def render(self):
        return rendered(
            ('<button phx-target="', '" phx-click="crash">Crash</button>'),
            self.myself,
        )

    async def disconnect(self) -> None:
        type(self).disconnects += 1


@live_view("/component-crash")
class CrashingComponentsLive(LiveView):
    disconnects = 0

    def render(self):
        return self.live_component(CrashingComponent, "crashing")

    async def disconnect(self) -> None:
        type(self).disconnects += 1


class CounterComponent(LiveComponent):
    mounts = 0
    updates = 0
    disconnects = 0
    mount_connections: list[bool] = []

    def __init__(self) -> None:
        self.count = 0
        self.label = ""

    @classmethod
    def reset(cls) -> None:
        cls.mounts = 0
        cls.updates = 0
        cls.disconnects = 0
        cls.mount_connections = []

    def mount(self) -> None:
        type(self).mounts += 1
        type(self).mount_connections.append(self.connected)

    def update(self, assigns: object) -> None:
        type(self).updates += 1
        assert isinstance(assigns, dict)
        label = cast(dict[str, object], assigns)["label"]
        assert isinstance(label, str)
        self.label = label

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "increment":
            raise UnknownEventError(event)
        self.count += 1

    def render(self):
        return (
            t'<button id="component-{self.id}" phx-target="{self.myself}" '
            t'phx-click="increment">{self.label}:{self.count}</button>'
        )

    async def disconnect(self) -> None:
        type(self).disconnects += 1


@live_view("/components")
class ComponentsLive(LiveView):
    def __init__(self) -> None:
        self.show_right = True

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "toggle_right":
            raise UnknownEventError(event)
        self.show_right = not self.show_right

    def render(self):
        left = self.live_component(
            CounterComponent,
            "left",
            {"label": "Left"},
        )
        right = (
            self.live_component(
                CounterComponent,
                "right",
                {"label": "Right"},
            )
            if self.show_right
            else ""
        )
        return (
            t"<section>{left}{right}"
            t'<button phx-click="toggle_right">toggle</button></section>'
        )


@live_view("/streams")
class StreamsLive(LiveView):
    async def mount(self, context: MountContext) -> None:
        del context
        self.stream_reset("activity-stream")
        self.stream_insert("activity-stream", "activity-1", self._item(1, "First"))
        self.stream_insert("activity-stream", "activity-2", self._item(2, "Second"))

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event == "prepend":
            self.stream_insert(
                "activity-stream",
                "activity-3",
                self._item(3, "Third"),
                at=0,
                limit=2,
            )
        elif event == "update":
            self.stream_insert(
                "activity-stream",
                "activity-1",
                self._item(1, "First updated"),
            )
        elif event == "delete":
            self.stream_delete("activity-stream", "activity-2")
        elif event == "reset":
            self.stream_reset("activity-stream")
            self.stream_insert(
                "activity-stream",
                "activity-9",
                self._item(9, "Reset item"),
            )
        elif event == "invalid_after_insert":
            self.stream_insert(
                "activity-stream",
                "activity-leaked",
                '<li id="activity-leaked">Leaked</li>',
            )
            raise UnknownEventError(event)
        else:
            raise UnknownEventError(event)

    def render(self):
        contents = self.stream_contents("activity-stream")
        return t'<ul id="activity-stream" phx-update="stream">{contents}</ul>'

    @staticmethod
    def _item(sequence: int, label: str):
        item_id = f"activity-{sequence}"
        return t'<li id="{item_id}">{label}</li>'


@live_view("/form")
class FormLive(LiveView):
    values: list[object] = []

    def __init__(self) -> None:
        self.received = 0

    async def handle_event(self, event: str, value: object) -> None:
        if event != "validate":
            raise UnknownEventError(event)
        type(self).values.append(value)
        self.received += 1

    def render(self):
        return rendered(
            (
                '<form id="profile" phx-change="validate">'
                '<input name="user[name]"><output>',
                "</output></form>",
            ),
            self.received,
        )


def _asgi(application: NestApplication) -> ASGIApp:
    return application.get_adapter(StarletteAdapter).app


async def _request(application: NestApplication, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=_asgi(application))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.get(path)


def _websocket_scope(
    path: str,
    *,
    origin: bytes | tuple[bytes, ...] = b"http://testserver",
) -> Any:
    origins = (origin,) if isinstance(origin, bytes) else origin
    return {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.5"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"host", b"testserver"), *[(b"origin", item) for item in origins]],
        "client": ("test", 1),
        "server": ("testserver", 80),
        "subprotocols": [],
    }


async def _call_websocket(
    application: NestApplication,
    path: str,
    *incoming: Message,
    origin: bytes | tuple[bytes, ...] = b"http://testserver",
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

    await _asgi(application)(
        _websocket_scope(path, origin=origin),
        receive,
        send,
    )
    return sent


def _receive_text(payload: object) -> Message:
    return {"type": "websocket.receive", "text": json.dumps(payload)}


def _disconnect() -> Message:
    return {"type": "websocket.disconnect", "code": 1000, "reason": ""}


def _decode_sent(messages: list[Message]) -> list[list[object]]:
    return [
        cast(list[object], json.loads(cast(str, message["text"])))
        for message in messages
        if message["type"] == "websocket.send"
    ]


_TOPIC = "lv:tori-live-root"


def _token(document: str) -> str:
    match = re.search(r'data-phx-session="([A-Za-z0-9_.-]+)"', document)
    assert match is not None
    return match[1]


def _join(token: str, *, ref: str = "1") -> Message:
    return _receive_text(
        [
            ref,
            ref,
            _TOPIC,
            "phx_join",
            {
                "url": "http://testserver/counter",
                "params": {"_mounts": 0, "_mount_attempts": 0},
                "session": token,
                "static": None,
                "sticky": False,
            },
        ]
    )


def _event(
    ref: str,
    event: str,
    *,
    value: object = None,
    cid: int | None = None,
    event_type: str = "click",
) -> Message:
    payload: dict[str, object] = {
        "type": event_type,
        "event": event,
        "value": {} if value is None else value,
    }
    if cid is not None:
        payload["cid"] = cid
    return _receive_text(["1", ref, _TOPIC, "event", payload])


def _reply_payload(frame: list[object]) -> dict[str, object]:
    assert frame[3] == "phx_reply"
    return cast(dict[str, object], frame[4])


def _response(frame: list[object]) -> dict[str, object]:
    payload = _reply_payload(frame)
    return cast(dict[str, object], payload["response"])


@pytest.mark.asyncio
async def test_components_require_render_context_and_unique_identity() -> None:
    class ProbeComponent(LiveComponent):
        def __init__(self) -> None:
            self.mounts = 0
            self.updates = 0
            self.disconnects = 0

        def mount(self) -> None:
            self.mounts += 1

        def update(self, assigns: object) -> None:
            del assigns
            self.updates += 1

        def render(self) -> str:
            return "<p>probe</p>"

        async def disconnect(self) -> None:
            self.disconnects += 1

    component = ProbeComponent()

    class DuplicateComponentsLive(LiveView):
        def render(self):
            rendered_component = self.live_component(
                ProbeComponent,
                "duplicate",
                factory=lambda: component,
            )
            self.live_component(ProbeComponent, "duplicate")
            return rendered_component

    page = DuplicateComponentsLive()
    with pytest.raises(LiveViewError, match="only be rendered"):
        page.live_component(ProbeComponent, "outside")
    with pytest.raises(LiveViewError, match="not attached"):
        _ = component.id
    with pytest.raises(LiveViewError, match="Duplicate LiveView component"):
        await page._render_liveview()

    assert component.mounts == 1
    assert component.updates == 1
    await page._disconnect_liveview_components()
    assert component.disconnects == 1


@pytest.mark.asyncio
async def test_components_require_exactly_one_root_element() -> None:
    class EmptyComponent(LiveComponent):
        def render(self) -> str:
            return ""

    class MultipleRootComponent(LiveComponent):
        def render(self) -> str:
            return "<p>first</p><p>second</p>"

    class SelfClosingComponent(LiveComponent):
        def render(self) -> str:
            return "<section/>"

    class InvalidComponentLive(LiveView):
        def __init__(self, component_type: type[LiveComponent]) -> None:
            self.component_type = component_type

        def render(self):
            return self.live_component(self.component_type, "invalid")

    for component_type in (
        EmptyComponent,
        MultipleRootComponent,
        SelfClosingComponent,
    ):
        page = InvalidComponentLive(component_type)
        with pytest.raises(LiveViewError, match="balanced root element"):
            await page._render_liveview()
        await page._disconnect_liveview_components()


@pytest.mark.asyncio
async def test_components_revive_until_phoenix_confirms_destruction() -> None:
    class StatefulComponent(LiveComponent):
        mounts = 0
        disconnects = 0

        def __init__(self) -> None:
            self.count = 0

        def mount(self) -> None:
            type(self).mounts += 1

        async def handle_event(self, event: str, value: object) -> None:
            del value
            if event != "increment":
                raise UnknownEventError(event)
            self.count += 1

        def render(self):
            return rendered(("<button>", "</button>"), self.count)

        async def disconnect(self) -> None:
            type(self).disconnects += 1

    class ToggleLive(LiveView):
        def __init__(self) -> None:
            self.show = True

        def render(self):
            component = (
                self.live_component(StatefulComponent, "counter") if self.show else ""
            )
            return rendered(("<section>", "</section>"), component)

    page = ToggleLive()
    await page._mount_liveview(MountContext(object(), {}, "/", True, QueryParams()))
    await page._render_liveview()
    first_cid = next(iter(page._liveview_components_by_cid))
    await page._handle_liveview_event(first_cid, "increment", {})

    page.show = False
    await page._render_liveview()
    page._prepare_liveview_component_destruction([first_cid])
    page.show = True
    await page._render_liveview()
    revived = page._liveview_components_by_cid[first_cid]
    assert isinstance(revived, StatefulComponent)
    assert revived.count == 1
    assert await page._destroy_liveview_components([first_cid]) == []
    assert StatefulComponent.mounts == 1
    assert StatefulComponent.disconnects == 0

    page.show = False
    await page._render_liveview()
    page._prepare_liveview_component_destruction([first_cid])
    assert await page._destroy_liveview_components([first_cid]) == [first_cid]
    assert StatefulComponent.disconnects == 1

    page.show = True
    await page._render_liveview()
    second_cid = next(iter(page._liveview_components_by_cid))
    assert second_cid != first_cid
    replacement = page._liveview_components_by_cid[second_cid]
    assert isinstance(replacement, StatefulComponent)
    assert replacement.count == 0
    assert StatefulComponent.mounts == 2
    await page._disconnect_liveview()
    assert StatefulComponent.disconnects == 2


def test_stream_operations_validate_and_render_disconnected_contents() -> None:
    page = StreamsLive()

    with pytest.raises(TypeError, match="container id must be a string"):
        page.stream_reset(cast(Any, 1))
    with pytest.raises(ValueError, match="container id cannot be empty"):
        page.stream_reset("")
    with pytest.raises(ValueError, match="item id cannot be empty"):
        page.stream_delete("activity-stream", "")
    with pytest.raises(ValueError, match="cannot contain ASCII whitespace"):
        page.stream_delete("activity-stream", "activity 1")
    with pytest.raises(ValueError, match="index must be -1 or greater"):
        page.stream_insert("activity-stream", "activity-1", "<li></li>", at=-2)
    with pytest.raises(ValueError, match="limit cannot be zero"):
        page.stream_insert("activity-stream", "activity-1", "<li></li>", limit=0)
    with pytest.raises(ValueError, match="balanced root element"):
        page.stream_insert(
            "activity-stream",
            "activity-1",
            '<li id="different">Different</li>',
        )
    with pytest.raises(ValueError, match="balanced root element"):
        page.stream_insert(
            "activity-stream",
            "activity-1",
            '<li id="activity-1">One</li><li id="activity-2">Two</li>',
        )
    with pytest.raises(ValueError, match="balanced root element"):
        page.stream_insert(
            "activity-stream",
            "activity-1",
            '<li id="different" id="activity-1">Different</li>',
        )

    page.stream_insert("activity-stream", "activity-1", page._item(1, "First"))
    page.stream_insert("activity-stream", "activity-2", page._item(2, "Second"))
    page.stream_insert(
        "activity-stream",
        "activity-1",
        page._item(1, "First updated"),
    )
    page.stream_delete("activity-stream", "activity-2")
    page.stream_insert(
        "activity-stream",
        "activity-3",
        page._item(3, "Third"),
        at=0,
        limit=2,
    )

    contents = page.stream_contents("activity-stream")
    assert contents.value.index("activity-3") < contents.value.index("activity-1")
    assert "First updated" in contents.value
    assert "activity-2" not in contents.value

    page.stream_reset("activity-stream")
    page.stream_insert("activity-stream", "activity-9", page._item(9, "Reset item"))
    reset_contents = page.stream_contents("activity-stream")
    assert "activity-9" in reset_contents.value
    assert "activity-1" not in reset_contents.value

    bounded = StreamsLive()
    for sequence in range(1, 5):
        bounded.stream_insert(
            "activity-stream",
            f"activity-{sequence}",
            bounded._item(sequence, str(sequence)),
            limit=-2 if sequence == 4 else None,
        )
    bounded.stream_insert(
        "activity-stream",
        "activity-5",
        bounded._item(5, "5"),
        at=99,
    )
    bounded_contents = bounded.stream_contents("activity-stream").value
    assert "activity-1" not in bounded_contents
    assert "activity-2" not in bounded_contents
    assert bounded_contents.index("activity-3") < bounded_contents.index("activity-4")
    assert bounded_contents.index("activity-4") < bounded_contents.index("activity-5")


def test_for_root_materializes_pages_as_request_scoped_normal_routes() -> None:
    descriptor = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[CounterLive],
    )
    spec = cast(ModuleSpec, descriptor.factory())

    assert descriptor.module is LiveViewModule
    assert descriptor.key == "default"
    page_provider = next(
        provider
        for provider in spec.providers
        if isinstance(provider, ClassProvider) and provider.token is CounterLive
    )
    assert page_provider.scope is Scope.REQUEST
    controllers = tuple(spec.controllers)
    assert len(controllers) == 2
    page_controller = next(
        controller
        for controller in controllers
        if get_route_metadata(cast(Any, controller).initial) is not None
    )
    assert get_controller_metadata(page_controller) is not None
    route_metadata = get_route_metadata(cast(Any, page_controller).initial)
    assert route_metadata is not None
    assert route_metadata.path == "/counter"
    gateway_provider = next(
        provider
        for provider in spec.providers
        if isinstance(provider, ClassProvider)
        and provider.use_class is not None
        and get_websocket_gateway_metadata(provider.use_class) is not None
    )
    gateway = gateway_provider.use_class
    assert gateway is not None
    gateway_metadata = get_websocket_gateway_metadata(gateway)
    assert gateway_metadata is not None
    assert gateway_metadata.path == "/_tori/live/websocket"


def test_for_root_rejects_invalid_and_conflicting_page_declarations() -> None:
    class Undeclared(LiveView):
        def render(self) -> str:
            return ""

    with pytest.raises(LiveViewConfigurationError, match="at least one"):
        LiveViewModule.for_root(LiveViewOptions(secret="s" * 32), pages=[])
    with pytest.raises(LiveViewConfigurationError, match="LiveView subclasses"):
        LiveViewModule.for_root(
            LiveViewOptions(secret="s" * 32),
            pages=[cast(Any, object)],
        )
    with pytest.raises(LiveViewConfigurationError, match="explicit @live_view"):
        LiveViewModule.for_root(
            LiveViewOptions(secret="s" * 32),
            pages=[Undeclared],
        )
    with pytest.raises(LiveViewConfigurationError, match="must be unique"):
        LiveViewModule.for_root(
            LiveViewOptions(secret="s" * 32),
            pages=[CounterLive, CounterLive],
        )
    with pytest.raises(LiveViewConfigurationError, match="must be unique"):
        LiveViewModule.for_root(
            LiveViewOptions(secret="s" * 32, client_path="/counter"),
            pages=[CounterLive],
        )

    first = live_view("/first")(
        type(
            "CollidingLive",
            (LiveView,),
            {"render": lambda self: "first", "__module__": __name__},
        )
    )
    second = live_view("/second")(
        type(
            "CollidingLive",
            (LiveView,),
            {"render": lambda self: "second", "__module__": __name__},
        )
    )
    with pytest.raises(LiveViewConfigurationError, match="identities must be unique"):
        LiveViewModule.for_root(
            LiveViewOptions(secret="s" * 32),
            pages=[first, second],
        )


@pytest.mark.asyncio
async def test_http_mount_serves_initial_html_and_pinned_phoenix_clients() -> None:
    CounterLive.mounts.clear()
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[CounterLive],
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/counter?start=2")
    client = await _request(application, "/_tori/live.js")

    assert page.status_code == 200
    assert page.headers["content-type"] == "text/html; charset=utf-8"
    assert page.headers["cache-control"] == "no-store"
    assert "<output>2</output>" in page.text
    assert '<title data-default="">Counter 2</title>' in page.text
    assert 'id="tori-live-root" data-phx-main' in page.text
    assert 'data-phx-static=""' in page.text
    assert 'data-tori-live-socket="/_tori/live"' in page.text
    assert '<script defer src="/_tori/live.js"></script>' in page.text
    assert re.search(r'data-phx-session="[A-Za-z0-9_.-]+"', page.text)
    assert client.status_code == 200
    assert client.headers["content-type"] == "text/javascript; charset=utf-8"
    assert "var Phoenix=" in client.text
    assert "var LiveView=" in client.text
    assert "new LiveView.LiveSocket" in client.text
    static = files("tori_py_liveview").joinpath("static")
    phoenix = static.joinpath("phoenix-1.8.13.min.js").read_bytes()
    phoenix_live_view = static.joinpath("phoenix_live_view-1.2.11.min.js").read_bytes()
    assert hashlib.sha256(phoenix).hexdigest() == (
        "b8702c214c5c7f2c476d827a22b5f337818ab7cb50d48b066a7a8c9691e8b923"
    )
    assert hashlib.sha256(phoenix_live_view).hexdigest() == (
        "04163ddbfc277452590a7a391c806e1c71883522b106e508b7a9da514c6c3b12"
    )
    assert phoenix in client.content
    assert phoenix_live_view in client.content
    assert CounterLive.mounts == [False]
    await application.shutdown()


@pytest.mark.asyncio
async def test_phoenix_channel_connects_renders_and_correlates_events() -> None:
    CounterLive.mounts.clear()
    CounterLive.disconnects = 0
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[CounterLive],
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/counter?start=2")
    token = _token(page.text)

    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join(token),
        _event("2", "increment"),
        _disconnect(),
    )
    assert sent[0]["type"] == "websocket.accept"
    messages = _decode_sent(sent)
    assert messages[0][:4] == ["1", "1", _TOPIC, "phx_reply"]
    join_payload = _reply_payload(messages[0])
    assert join_payload["status"] == "ok"
    join_response = _response(messages[0])
    assert join_response["liveview_version"] == "1.2.11"
    snapshot = cast(dict[str, object], join_response["rendered"])
    assert snapshot == {
        "s": [
            '<section><button phx-click="increment">+</button><output>',
            "</output></section>",
        ],
        "0": "2",
        "t": "Counter 2",
    }
    assert messages[1][:4] == ["1", "2", _TOPIC, "phx_reply"]
    event_payload = _reply_payload(messages[1])
    assert event_payload["status"] == "ok"
    assert _response(messages[1])["diff"] == {
        "s": snapshot["s"],
        "0": "3",
        "t": "Counter 3",
    }
    assert CounterLive.mounts == [False, True]
    assert CounterLive.disconnects == 1
    await application.shutdown()


@pytest.mark.asyncio
async def test_phoenix_form_event_decodes_values_and_target_metadata() -> None:
    FormLive.values.clear()
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[FormLive],
        key="form",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/form")
    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join(_token(page.text)),
        _receive_text(
            [
                "1",
                "2",
                _TOPIC,
                "event",
                {
                    "type": "form",
                    "event": "validate",
                    "value": (
                        "user%5Bname%5D=Tori&tag=one&tag=two&"
                        "role%5B%5D=admin&role%5B%5D=editor&filter%5B=open"
                    ),
                    "meta": {"_target": "user[name]"},
                    "uploads": {},
                },
            ]
        ),
        _disconnect(),
    )

    assert FormLive.values == [
        {
            "user": {"name": "Tori"},
            "tag": "two",
            "role": ["admin", "editor"],
            "filter[": "open",
            "_target": ["user", "name"],
        }
    ]
    diff = cast(dict[str, object], _response(_decode_sent(sent)[1])["diff"])
    assert diff["0"] == "1"
    await application.shutdown()


@pytest.mark.asyncio
async def test_components_keep_state_route_targets_and_cleanup() -> None:
    CounterComponent.reset()
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[ComponentsLive],
        key="components",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/components")
    token = _token(page.text)
    assert "Left:0" in page.text
    assert "Right:0" in page.text
    assert CounterComponent.mounts == 2
    assert CounterComponent.disconnects == 2

    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join(token),
        _event("2", "increment", cid=1),
        _event("3", "increment", cid=2),
        _event("4", "increment", cid=999_999),
        _event("5", "missing", cid=1),
        _event("6", "toggle_right"),
        _receive_text(["1", "7", _TOPIC, "cids_will_destroy", {"cids": [2]}]),
        _receive_text(["1", "8", _TOPIC, "cids_destroyed", {"cids": [2]}]),
        _event("9", "toggle_right"),
        _disconnect(),
    )
    messages = _decode_sent(sent)
    snapshot = cast(dict[str, object], _response(messages[0])["rendered"])
    components = cast(dict[str, dict[str, object]], snapshot["c"])
    assert snapshot["0"] == 1
    assert snapshot["1"] == 2
    assert components["1"]["1"] == "1"
    assert components["1"]["2"] == "Left"
    assert components["1"]["3"] == "0"
    assert components["1"]["r"] == 1
    assert components["2"]["2"] == "Right"

    left_diff = cast(dict[str, object], _response(messages[1])["diff"])
    left_components = cast(dict[str, dict[str, object]], left_diff["c"])
    assert left_components["1"]["3"] == "1"
    right_diff = cast(dict[str, object], _response(messages[2])["diff"])
    right_components = cast(dict[str, dict[str, object]], right_diff["c"])
    assert right_components["2"]["3"] == "1"
    assert _reply_payload(messages[3]) == {
        "status": "ok",
        "response": {"reason": "unknown_target"},
    }
    assert _reply_payload(messages[4]) == {
        "status": "ok",
        "response": {"reason": "unknown_event"},
    }
    removed = cast(dict[str, object], _response(messages[5])["diff"])
    assert removed["1"] == ""
    assert set(cast(dict[str, object], removed["c"])) == {"1"}
    assert _response(messages[6]) == {}
    assert _response(messages[7]) == {"cids": [2]}
    restored = cast(dict[str, object], _response(messages[8])["diff"])
    assert restored["1"] == 3
    restored_components = cast(dict[str, dict[str, object]], restored["c"])
    assert restored_components["3"]["2"] == "Right"
    assert restored_components["3"]["3"] == "0"
    assert CounterComponent.mounts == 5
    assert CounterComponent.mount_connections == [False, False, True, True, True]
    assert CounterComponent.updates == 11
    assert CounterComponent.disconnects == 5
    await application.shutdown()


@pytest.mark.asyncio
async def test_streams_render_initial_html_and_send_phoenix_stream_tuples() -> None:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[StreamsLive],
        key="streams",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/streams")
    token = _token(page.text)
    assert '<li id="activity-1">First</li>' in page.text
    assert '<li id="activity-2">Second</li>' in page.text

    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join(token),
        _event("2", "prepend"),
        _event("3", "update"),
        _event("4", "invalid_after_insert"),
        _event("5", "delete"),
        _event("6", "reset"),
        _disconnect(),
    )
    messages = _decode_sent(sent)
    initial = cast(
        dict[str, object],
        cast(dict[str, object], _response(messages[0])["rendered"])["0"],
    )
    assert initial["k"] == {
        "0": {"0": '<li id="activity-1">First</li>'},
        "1": {"0": '<li id="activity-2">Second</li>'},
        "kc": 2,
    }
    assert initial["stream"] == [
        "activity-stream",
        [
            ["activity-1", -1, None, None],
            ["activity-2", -1, None, None],
        ],
        [],
        True,
    ]
    prepend = cast(
        dict[str, object],
        cast(dict[str, object], _response(messages[1])["diff"])["0"],
    )
    assert prepend["stream"] == [
        "activity-stream",
        [["activity-3", 0, 2, None]],
        [],
    ]
    update = cast(
        dict[str, object],
        cast(dict[str, object], _response(messages[2])["diff"])["0"],
    )
    assert (
        cast(dict[str, object], cast(dict[str, object], update["k"])["0"])["0"]
        == '<li id="activity-1">First updated</li>'
    )
    assert _reply_payload(messages[3]) == {
        "status": "ok",
        "response": {"reason": "unknown_event"},
    }
    delete = cast(
        dict[str, object],
        cast(dict[str, object], _response(messages[4])["diff"])["0"],
    )
    assert delete["stream"] == ["activity-stream", [], ["activity-2"]]
    reset = cast(
        dict[str, object],
        cast(dict[str, object], _response(messages[5])["diff"])["0"],
    )
    assert reset["stream"] == [
        "activity-stream",
        [["activity-9", -1, None, None]],
        [],
        True,
    ]
    await application.shutdown()


@pytest.mark.asyncio
async def test_phoenix_channel_echoes_heartbeats_and_acknowledges_leave() -> None:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[CounterLive],
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/counter")
    token = _token(page.text)

    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join(token),
        _receive_text([None, "2", "phoenix", "heartbeat", {}]),
        _receive_text(["1", "3", _TOPIC, "phx_leave", {}]),
    )
    messages = _decode_sent(sent)
    assert messages[1] == [
        None,
        "2",
        "phoenix",
        "phx_reply",
        {"status": "ok", "response": {}},
    ]
    assert messages[2] == [
        "1",
        "3",
        _TOPIC,
        "phx_reply",
        {"status": "ok", "response": {}},
    ]
    await application.shutdown()


@pytest.mark.asyncio
async def test_phoenix_render_omits_an_absent_title() -> None:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[UntitledLive],
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/untitled")
    token = _token(page.text)

    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join(token),
        _disconnect(),
    )
    render_message = cast(
        dict[str, object],
        _response(_decode_sent(sent)[0])["rendered"],
    )
    assert "title" not in render_message
    assert render_message["t"] == ""
    await application.shutdown()


@pytest.mark.asyncio
async def test_phoenix_channel_enforces_origin_type_and_size_before_dispatch() -> None:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(
            secret="s" * 32,
            allowed_origins=("https://trusted.example",),
            max_message_bytes=10,
        ),
        pages=[CounterLive],
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/counter")
    token = _token(page.text)

    allowed = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _disconnect(),
        origin=b"https://trusted.example",
    )
    assert allowed[0]["type"] == "websocket.accept"
    disallowed = await _call_websocket(
        application,
        "/_tori/live/websocket",
        origin=b"http://testserver/path?query=1",
    )
    assert disallowed == [{"type": "websocket.close", "code": 1008, "reason": ""}]
    duplicate_origin = await _call_websocket(
        application,
        "/_tori/live/websocket",
        origin=(b"https://trusted.example", b"http://attacker.example"),
    )
    assert duplicate_origin[-1]["code"] == 1008

    oversized = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join(token),
        origin=b"https://trusted.example",
    )
    assert oversized[-1]["type"] == "websocket.close"
    assert oversized[-1]["code"] == 1009

    binary = await _call_websocket(
        application,
        "/_tori/live/websocket",
        {"type": "websocket.receive", "bytes": b"{}"},
        origin=b"https://trusted.example",
    )
    assert binary[-1]["type"] == "websocket.close"
    assert binary[-1]["code"] == 1003
    await application.shutdown()


@pytest.mark.asyncio
async def test_phoenix_channel_uses_policy_and_going_away_timeout_closes() -> None:
    join_timeout_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32, join_timeout_seconds=0.01),
        pages=[CounterLive],
        key="join-timeout",
    )

    @module(imports=[join_timeout_module])
    class JoinTimeoutRoot:
        pass

    join_application = await NestApplication.create(
        JoinTimeoutRoot,
        adapter=StarletteAdapter(),
    )
    await join_application.start()
    join_timeout = await _call_websocket(
        join_application,
        "/_tori/live/websocket",
    )
    assert join_timeout[-1]["type"] == "websocket.close"
    assert join_timeout[-1]["code"] == 1008
    await join_application.shutdown()

    idle_timeout_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32, idle_timeout_seconds=0.01),
        pages=[CounterLive],
        key="idle-timeout",
    )

    @module(imports=[idle_timeout_module])
    class IdleTimeoutRoot:
        pass

    idle_application = await NestApplication.create(
        IdleTimeoutRoot,
        adapter=StarletteAdapter(),
    )
    await idle_application.start()
    page = await _request(idle_application, "/counter")
    token = _token(page.text)
    idle_timeout = await _call_websocket(
        idle_application,
        "/_tori/live/websocket",
        _join(token),
    )
    assert idle_timeout[-1]["type"] == "websocket.close"
    assert idle_timeout[-1]["code"] == 1001
    await idle_application.shutdown()


@pytest.mark.asyncio
async def test_phoenix_channel_reports_unknown_events_and_targets() -> None:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[CounterLive],
        key="event-errors",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/counter")
    token = _token(page.text)
    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join(token),
        _event("2", "increment", cid=7),
        _event("3", "missing"),
        _disconnect(),
    )
    assert [_reply_payload(frame) for frame in _decode_sent(sent)[1:]] == [
        {"status": "ok", "response": {"reason": "unknown_target"}},
        {"status": "ok", "response": {"reason": "unknown_event"}},
    ]
    await application.shutdown()


@pytest.mark.asyncio
async def test_phoenix_channel_rejects_malformed_messages_and_invalid_tokens() -> None:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[CounterLive],
        key="invalid-input",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    malformed = await _call_websocket(
        application,
        "/_tori/live/websocket",
        {"type": "websocket.receive", "text": "{"},
    )
    assert malformed[-1]["code"] == 1002
    nonstandard_json = await _call_websocket(
        application,
        "/_tori/live/websocket",
        {
            "type": "websocket.receive",
            "text": '["1","1","lv:tori-live-root","phx_join",{"x":NaN}]',
        },
    )
    assert nonstandard_json[-1]["code"] == 1002
    invalid_token = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join("invalid"),
    )
    assert _reply_payload(_decode_sent(invalid_token)[0]) == {
        "status": "error",
        "response": {"reason": "unauthorized"},
    }

    page = await _request(application, "/counter")
    token = _token(page.text)
    unsafe_integer = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join(token),
        _event("2", "increment", cid=2**53),
    )
    assert unsafe_integer[-1]["code"] == 1002
    invalid_unicode = await _call_websocket(
        application,
        "/_tori/live/websocket",
        {"type": "websocket.receive", "text": "\ud800"},
    )
    assert invalid_unicode[-1]["code"] == 1002
    await application.shutdown()


@pytest.mark.asyncio
async def test_phoenix_channel_closes_on_unexpected_handler_failures() -> None:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[CrashingLive],
        key="handler-failure",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/crash")
    token = _token(page.text)
    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join(token),
        _event("2", "crash"),
    )
    assert sent[-1]["type"] == "websocket.close"
    assert sent[-1]["code"] == 1011
    await application.shutdown()


@pytest.mark.asyncio
async def test_phoenix_channel_cleans_up_after_component_handler_failures() -> None:
    CrashingComponent.disconnects = 0
    CrashingComponentsLive.disconnects = 0
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[CrashingComponentsLive],
        key="component-handler-failure",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/component-crash")
    token = _token(page.text)
    assert CrashingComponent.disconnects == 1

    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join(token),
        _event("2", "crash", cid=1),
    )
    assert sent[-1]["type"] == "websocket.close"
    assert sent[-1]["code"] == 1011
    assert CrashingComponent.disconnects == 2
    assert CrashingComponentsLive.disconnects == 1
    await application.shutdown()
