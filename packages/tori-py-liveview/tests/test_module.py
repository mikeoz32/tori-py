from __future__ import annotations

import asyncio
import hashlib
import json
import re
from importlib.resources import files
from typing import Any, cast

import httpx
import pytest
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
        return rendered(
            (
                '<button data-opal-click="increment">+</button><output>',
                "</output>",
            ),
            self.count,
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
            ('<button data-opal-target="', '" data-opal-click="crash">Crash</button>'),
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
        return rendered(
            (
                '<button id="component-',
                '" data-opal-target="',
                '" data-opal-click="increment">',
                ":",
                "</button>",
            ),
            self.id,
            self.myself,
            self.label,
            self.count,
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
        return rendered(
            (
                "<section>",
                "",
                '<button data-opal-click="toggle_right">toggle</button></section>',
            ),
            left,
            right,
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
        return rendered(
            ('<ul id="activity-stream" data-opal-stream>', "</ul>"),
            self.stream_contents("activity-stream"),
        )

    @staticmethod
    def _item(sequence: int, label: str):
        item_id = f"activity-{sequence}"
        return rendered(
            ('<li id="', '" data-opal-key="', '">', "</li>"),
            item_id,
            item_id,
            label,
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


def _receive_text(payload: dict[str, object]) -> Message:
    return {"type": "websocket.receive", "text": json.dumps(payload)}


def _disconnect() -> Message:
    return {"type": "websocket.disconnect", "code": 1000, "reason": ""}


def _decode_sent(messages: list[Message]) -> list[dict[str, object]]:
    return [
        cast(dict[str, object], json.loads(cast(str, message["text"])))
        for message in messages
        if message["type"] == "websocket.send"
    ]


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


def test_stream_operations_validate_and_render_disconnected_contents() -> None:
    page = StreamsLive()

    with pytest.raises(TypeError, match="container id must be a string"):
        page.stream_reset(cast(Any, 1))
    with pytest.raises(ValueError, match="container id cannot be empty"):
        page.stream_reset("")
    with pytest.raises(ValueError, match="item id cannot be empty"):
        page.stream_delete("activity-stream", "")
    with pytest.raises(ValueError, match="index must be -1 or greater"):
        page.stream_insert("activity-stream", "activity-1", "<li></li>", at=-2)
    with pytest.raises(ValueError, match="limit cannot be zero"):
        page.stream_insert("activity-stream", "activity-1", "<li></li>", limit=0)

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
    assert gateway_metadata.path == "/_tori/live"


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
async def test_http_mount_serves_initial_html_and_pinned_opal_client() -> None:
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
    assert "<title>Counter 2</title>" in page.text
    assert "data-opal-live-root" in page.text
    assert 'data-opal-socket="/_tori/live"' in page.text
    assert '<script type="module" src="/_tori/live.js"></script>' in page.text
    assert re.search(r'data-opal-token="[A-Za-z0-9_.-]+"', page.text)
    assert client.status_code == 200
    assert client.headers["content-type"] == "text/javascript; charset=utf-8"
    assert "const PROTOCOL_VERSION = 2;" in client.text
    expected_client = (
        files("tori_py_liveview").joinpath("static/opal_live_view.js").read_bytes()
    )
    assert client.content == expected_client
    assert hashlib.sha256(expected_client).hexdigest() == (
        "abd50912b09bbfdfc849462d66559de57a706eb63651b08e3d412738becd5653"
    )
    assert CounterLive.mounts == [False]
    await application.shutdown()


@pytest.mark.asyncio
async def test_protocol_v2_connects_renders_diffs_and_correlates_events() -> None:
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
    token = re.search(r'data-opal-token="([A-Za-z0-9_.-]+)"', page.text)
    assert token is not None

    sent = await _call_websocket(
        application,
        "/_tori/live",
        _receive_text({"type": "join", "protocol": 2, "token": token[1]}),
        _receive_text(
            {
                "type": "event",
                "event": "increment",
                "value": {},
                "target": None,
                "version": 0,
                "ref": 1,
            }
        ),
        _disconnect(),
    )
    assert sent[0]["type"] == "websocket.accept"
    messages = _decode_sent(sent)
    assert messages[0]["type"] == "render"
    assert messages[0]["protocol"] == 2
    assert messages[0]["version"] == 0
    snapshot = cast(dict[str, object], messages[0]["rendered"])
    assert snapshot["dynamics"] == ["2"]
    assert messages[0]["title"] == "Counter 2"
    assert messages[1] == {
        "type": "render",
        "protocol": 2,
        "version": 1,
        "fingerprint": snapshot["fingerprint"],
        "diff": {"0": "3"},
        "ref": 1,
        "status": "ok",
        "title": "Counter 3",
    }
    assert CounterLive.mounts == [False, True]
    assert CounterLive.disconnects == 1
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
    token = re.search(r'data-opal-token="([A-Za-z0-9_.-]+)"', page.text)
    assert token is not None
    assert "Left:0" in page.text
    assert "Right:0" in page.text
    assert CounterComponent.mounts == 2
    assert CounterComponent.disconnects == 2

    sent = await _call_websocket(
        application,
        "/_tori/live",
        _receive_text({"type": "join", "protocol": 2, "token": token[1]}),
        _receive_text(
            {
                "type": "event",
                "event": "increment",
                "target": 1,
                "value": None,
                "version": 0,
                "ref": 1,
            }
        ),
        _receive_text(
            {
                "type": "event",
                "event": "increment",
                "target": 2,
                "value": None,
                "version": 1,
                "ref": 2,
            }
        ),
        _receive_text(
            {
                "type": "event",
                "event": "increment",
                "target": 999_999,
                "value": None,
                "version": 2,
                "ref": 3,
            }
        ),
        _receive_text(
            {
                "type": "event",
                "event": "missing",
                "target": 1,
                "value": None,
                "version": 2,
                "ref": 4,
            }
        ),
        _receive_text(
            {
                "type": "event",
                "event": "toggle_right",
                "target": None,
                "value": None,
                "version": 2,
                "ref": 5,
            }
        ),
        _receive_text(
            {
                "type": "event",
                "event": "toggle_right",
                "target": None,
                "value": None,
                "version": 3,
                "ref": 6,
            }
        ),
        _disconnect(),
    )
    messages = _decode_sent(sent)
    snapshot = cast(dict[str, object], messages[0]["rendered"])
    initial_dynamics = cast(list[str], snapshot["dynamics"])
    assert 'id="component-left" data-opal-target="1"' in initial_dynamics[0]
    assert 'id="component-right" data-opal-target="2"' in initial_dynamics[1]
    assert messages[1]["diff"] == {
        "0": (
            '<button id="component-left" data-opal-target="1" '
            'data-opal-click="increment">Left:1</button>'
        )
    }
    assert messages[2]["diff"] == {
        "1": (
            '<button id="component-right" data-opal-target="2" '
            'data-opal-click="increment">Right:1</button>'
        )
    }
    assert messages[3] == {
        "type": "error",
        "reason": "unknown_target",
        "ref": 3,
    }
    assert messages[4] == {
        "type": "error",
        "reason": "unknown_event",
        "ref": 4,
    }
    assert messages[5]["version"] == 3
    assert messages[5]["diff"] == {"1": ""}
    restored = cast(dict[str, str], messages[6]["diff"])["1"]
    assert "Right:0" in restored
    assert 'data-opal-target="3"' in restored
    assert CounterComponent.mounts == 5
    assert CounterComponent.mount_connections == [False, False, True, True, True]
    assert CounterComponent.updates == 11
    assert CounterComponent.disconnects == 5
    await application.shutdown()


@pytest.mark.asyncio
async def test_streams_render_initial_html_and_send_ordered_protocol_operations() -> (
    None
):
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
    token = re.search(r'data-opal-token="([A-Za-z0-9_.-]+)"', page.text)
    assert token is not None
    assert '<li id="activity-1" data-opal-key="activity-1">First</li>' in page.text
    assert '<li id="activity-2" data-opal-key="activity-2">Second</li>' in page.text

    sent = await _call_websocket(
        application,
        "/_tori/live",
        _receive_text({"type": "join", "protocol": 2, "token": token[1]}),
        _receive_text(
            {
                "type": "event",
                "event": "prepend",
                "value": None,
                "version": 0,
                "ref": 1,
            }
        ),
        _receive_text(
            {
                "type": "event",
                "event": "update",
                "value": None,
                "version": 1,
                "ref": 2,
            }
        ),
        _receive_text(
            {
                "type": "event",
                "event": "invalid_after_insert",
                "value": None,
                "version": 2,
                "ref": 3,
            }
        ),
        _receive_text(
            {
                "type": "event",
                "event": "delete",
                "value": None,
                "version": 2,
                "ref": 4,
            }
        ),
        _receive_text(
            {
                "type": "event",
                "event": "reset",
                "value": None,
                "version": 3,
                "ref": 5,
            }
        ),
        _disconnect(),
    )
    messages = _decode_sent(sent)
    assert messages[0]["streams"] == [
        {"op": "reset", "container": "activity-stream"},
        {
            "op": "insert",
            "container": "activity-stream",
            "id": "activity-1",
            "html": '<li id="activity-1" data-opal-key="activity-1">First</li>',
            "at": -1,
        },
        {
            "op": "insert",
            "container": "activity-stream",
            "id": "activity-2",
            "html": '<li id="activity-2" data-opal-key="activity-2">Second</li>',
            "at": -1,
        },
    ]
    assert messages[1]["streams"] == [
        {
            "op": "insert",
            "container": "activity-stream",
            "id": "activity-3",
            "html": '<li id="activity-3" data-opal-key="activity-3">Third</li>',
            "at": 0,
            "limit": 2,
        }
    ]
    assert cast(list[dict[str, object]], messages[2]["streams"])[0]["html"] == (
        '<li id="activity-1" data-opal-key="activity-1">First updated</li>'
    )
    assert messages[3] == {
        "type": "error",
        "reason": "unknown_event",
        "ref": 3,
    }
    assert messages[4]["streams"] == [
        {"op": "delete", "container": "activity-stream", "id": "activity-2"}
    ]
    assert messages[5]["streams"] == [
        {"op": "reset", "container": "activity-stream"},
        {
            "op": "insert",
            "container": "activity-stream",
            "id": "activity-9",
            "html": '<li id="activity-9" data-opal-key="activity-9">Reset item</li>',
            "at": -1,
        },
    ]
    await application.shutdown()


@pytest.mark.asyncio
async def test_protocol_v2_resynchronizes_stale_events_and_echoes_heartbeats() -> None:
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
    token = re.search(r'data-opal-token="([A-Za-z0-9_.-]+)"', page.text)
    assert token is not None

    sent = await _call_websocket(
        application,
        "/_tori/live",
        _receive_text({"type": "join", "protocol": 2, "token": token[1]}),
        _receive_text(
            {
                "type": "event",
                "event": "increment",
                "value": {},
                "version": 99,
                "ref": 1,
            }
        ),
        _receive_text({"type": "heartbeat", "ref": 2}),
        _disconnect(),
    )
    messages = _decode_sent(sent)
    assert messages[1]["version"] == 0
    assert messages[1]["diff"] == {}
    assert messages[1]["ref"] == 1
    assert messages[1]["status"] == "stale"
    assert messages[2] == {"type": "heartbeat", "ref": 2}
    await application.shutdown()


@pytest.mark.asyncio
async def test_protocol_omits_an_absent_title() -> None:
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
    token = re.search(r'data-opal-token="([A-Za-z0-9_.-]+)"', page.text)
    assert token is not None

    sent = await _call_websocket(
        application,
        "/_tori/live",
        _receive_text({"type": "join", "protocol": 2, "token": token[1]}),
        _disconnect(),
    )
    render_message = _decode_sent(sent)[0]
    assert "title" not in render_message
    await application.shutdown()


@pytest.mark.asyncio
async def test_protocol_enforces_origin_message_type_and_size_before_dispatch() -> None:
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
    token = re.search(r'data-opal-token="([A-Za-z0-9_.-]+)"', page.text)
    assert token is not None

    allowed = await _call_websocket(
        application,
        "/_tori/live",
        _disconnect(),
        origin=b"https://trusted.example",
    )
    assert allowed[0]["type"] == "websocket.accept"
    disallowed = await _call_websocket(
        application,
        "/_tori/live",
        origin=b"http://testserver/path?query=1",
    )
    assert disallowed == [{"type": "websocket.close", "code": 1008, "reason": ""}]
    duplicate_origin = await _call_websocket(
        application,
        "/_tori/live",
        origin=(b"https://trusted.example", b"http://attacker.example"),
    )
    assert duplicate_origin[-1]["code"] == 1008

    oversized = await _call_websocket(
        application,
        "/_tori/live",
        _receive_text({"type": "join", "protocol": 2, "token": token[1]}),
        origin=b"https://trusted.example",
    )
    assert oversized[-1]["type"] == "websocket.close"
    assert oversized[-1]["code"] == 1009

    binary = await _call_websocket(
        application,
        "/_tori/live",
        {"type": "websocket.receive", "bytes": b"{}"},
        origin=b"https://trusted.example",
    )
    assert binary[-1]["type"] == "websocket.close"
    assert binary[-1]["code"] == 1003
    await application.shutdown()


@pytest.mark.asyncio
async def test_protocol_uses_policy_and_going_away_closes_for_timeouts() -> None:
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
    join_timeout = await _call_websocket(join_application, "/_tori/live")
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
    token = re.search(r'data-opal-token="([A-Za-z0-9_.-]+)"', page.text)
    assert token is not None
    idle_timeout = await _call_websocket(
        idle_application,
        "/_tori/live",
        _receive_text({"type": "join", "protocol": 2, "token": token[1]}),
    )
    assert idle_timeout[-1]["type"] == "websocket.close"
    assert idle_timeout[-1]["code"] == 1001
    await idle_application.shutdown()


@pytest.mark.asyncio
async def test_protocol_reports_unsupported_events_and_targets_without_mutation() -> (
    None
):
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
    token = re.search(r'data-opal-token="([A-Za-z0-9_.-]+)"', page.text)
    assert token is not None
    sent = await _call_websocket(
        application,
        "/_tori/live",
        _receive_text({"type": "join", "protocol": 2, "token": token[1]}),
        _receive_text(
            {
                "type": "event",
                "event": "increment",
                "target": 7,
                "version": 0,
                "ref": 1,
            }
        ),
        _receive_text(
            {
                "type": "event",
                "event": "missing",
                "version": 0,
                "ref": 2,
            }
        ),
        _disconnect(),
    )
    assert _decode_sent(sent)[1:] == [
        {"type": "error", "reason": "unknown_target", "ref": 1},
        {"type": "error", "reason": "unknown_event", "ref": 2},
    ]
    await application.shutdown()


@pytest.mark.asyncio
async def test_protocol_rejects_malformed_messages_and_invalid_tokens() -> None:
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
        "/_tori/live",
        {"type": "websocket.receive", "text": "{"},
    )
    assert malformed[-1]["code"] == 1002
    nonstandard_json = await _call_websocket(
        application,
        "/_tori/live",
        {
            "type": "websocket.receive",
            "text": '{"type":"join","protocol":2,"token":"invalid","x":NaN}',
        },
    )
    assert nonstandard_json[-1]["code"] == 1002
    invalid_token = await _call_websocket(
        application,
        "/_tori/live",
        _receive_text({"type": "join", "protocol": 2, "token": "invalid"}),
    )
    assert invalid_token[-1]["code"] == 1008

    page = await _request(application, "/counter")
    token = re.search(r'data-opal-token="([A-Za-z0-9_.-]+)"', page.text)
    assert token is not None
    unsafe_integer = await _call_websocket(
        application,
        "/_tori/live",
        _receive_text({"type": "join", "protocol": 2, "token": token[1]}),
        _receive_text(
            {
                "type": "event",
                "event": "increment",
                "version": 0,
                "ref": 2**53,
            }
        ),
    )
    assert unsafe_integer[-1]["code"] == 1002
    invalid_unicode = await _call_websocket(
        application,
        "/_tori/live",
        {"type": "websocket.receive", "text": "\ud800"},
    )
    assert invalid_unicode[-1]["code"] == 1002
    await application.shutdown()


@pytest.mark.asyncio
async def test_protocol_closes_on_unexpected_handler_failures() -> None:
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
    token = re.search(r'data-opal-token="([A-Za-z0-9_.-]+)"', page.text)
    assert token is not None
    sent = await _call_websocket(
        application,
        "/_tori/live",
        _receive_text({"type": "join", "protocol": 2, "token": token[1]}),
        _receive_text(
            {
                "type": "event",
                "event": "crash",
                "version": 0,
                "ref": 1,
            }
        ),
    )
    assert sent[-1]["type"] == "websocket.close"
    assert sent[-1]["code"] == 1011
    await application.shutdown()


@pytest.mark.asyncio
async def test_protocol_cleans_up_after_component_handler_failures() -> None:
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
    token = re.search(r'data-opal-token="([A-Za-z0-9_.-]+)"', page.text)
    assert token is not None
    assert CrashingComponent.disconnects == 1

    sent = await _call_websocket(
        application,
        "/_tori/live",
        _receive_text({"type": "join", "protocol": 2, "token": token[1]}),
        _receive_text(
            {
                "type": "event",
                "event": "crash",
                "target": 1,
                "value": None,
                "version": 0,
                "ref": 1,
            }
        ),
    )
    assert sent[-1]["type"] == "websocket.close"
    assert sent[-1]["code"] == 1011
    assert CrashingComponent.disconnects == 2
    assert CrashingComponentsLive.disconnects == 1
    await application.shutdown()
