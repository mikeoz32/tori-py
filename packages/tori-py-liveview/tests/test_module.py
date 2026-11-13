from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from importlib.resources import files
from typing import Annotated, Any, ClassVar, cast

import httpx
import pytest
from starlette.datastructures import QueryParams
from starlette.types import ASGIApp, Message
from tori_py import (
    ClassProvider,
    Inject,
    MethodInvocationContext,
    ModuleSpec,
    NestApplication,
    Scope,
    get_controller_metadata,
    get_route_metadata,
    get_websocket_gateway_metadata,
    module,
    use_method_interceptors,
)
from tori_py.http import HttpException
from tori_py.starlette import StarletteAdapter
from tori_py_liveview import (
    AsyncResult,
    LiveComponent,
    LiveView,
    LiveViewConfigurationError,
    LiveViewError,
    LiveViewModule,
    LiveViewOptions,
    MountContext,
    UnknownAsyncError,
    UnknownEventError,
    UnknownInfoError,
    fragment,
    live_view,
    rendered,
)
from tori_py_liveview._diff import _RenderState
from tori_py_liveview.endpoint import _child_signer, _ChildTask
from tori_py_liveview.page import _AsyncTask
from tori_py_liveview.tokens import (
    ChildTokenCodec,
    FlashTokenCodec,
    MountTokenCodec,
    ReloadTokenCodec,
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


class LeafComponent(LiveComponent):
    disconnects: ClassVar[list[str]] = []

    def __init__(self) -> None:
        self.label = ""
        self.count = 0

    def update(self, assigns: object) -> None:
        values = cast(dict[str, object], assigns)
        self.label = cast(str, values.get("label", self.label))
        self.count = cast(int, values.get("count", self.count))

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "bump":
            raise UnknownEventError(event)
        self.count += 1

    def render(self):
        return (
            t'<li id="leaf-{self.id}" phx-click="bump" '
            t'phx-target="{self.myself}">{self.label}:{self.count}</li>'
        )

    async def disconnect(self) -> None:
        type(self).disconnects.append(self.id)


class BranchComponent(LiveComponent):
    disconnects: ClassVar[list[str]] = []

    def __init__(self) -> None:
        self.leaves = ("a", "b")

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "drop":
            raise UnknownEventError(event)
        self.leaves = self.leaves[:1]

    def render(self):
        leaves = fragment(
            self.live_component(LeafComponent, leaf, {"label": leaf.upper()})
            for leaf in self.leaves
        )
        return t'<ul id="branch-{self.id}" phx-target="{self.myself}">{leaves}</ul>'

    async def disconnect(self) -> None:
        type(self).disconnects.append(self.id)


@live_view("/nested")
class NestedLive(LiveView):
    def __init__(self) -> None:
        self.show = True

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event == "toggle":
            self.show = not self.show
        elif event == "recount":
            # The branch passes only labels, so the count it leaves alone stays.
            self.send_update(LeafComponent, "a", {"count": 5})
        else:
            raise UnknownEventError(event)

    def render(self):
        branch = self.live_component(BranchComponent, "tree") if self.show else ""
        return t"<main>{branch}</main>"


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


@live_view("/server-updates")
class ServerUpdatesLive(LiveView):
    connected_page: ClassVar[ServerUpdatesLive | None] = None
    disconnect_send_results: ClassVar[list[bool]] = []
    mounted: ClassVar[asyncio.Event]

    def __init__(self) -> None:
        self.value = 0

    @classmethod
    def reset(cls) -> None:
        cls.connected_page = None
        cls.disconnect_send_results = []
        cls.mounted = asyncio.Event()

    async def mount(self, context: MountContext) -> None:
        if context.connected:
            type(self).connected_page = self
            type(self).mounted.set()

    async def handle_info(self, name: str, value: object) -> None:
        if name != "set" or type(value) is not int:
            await super().handle_info(name, value)
            return
        self.value = value

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "increment":
            raise UnknownEventError(event)
        self.value += 1

    async def disconnect(self) -> None:
        type(self).disconnect_send_results.append(self.send_info("set", 9))

    def render(self):
        return rendered(("<output>", "</output>"), self.value)


class EchoComponent(LiveComponent):
    def __init__(self) -> None:
        self.value = ""

    def update(self, assigns: object) -> None:
        if isinstance(assigns, dict) and "value" in assigns:
            self.value = str(cast(dict[str, object], assigns)["value"])

    async def handle_event(self, event: str, value: object) -> Mapping[str, object]:
        if event != "echo":
            raise UnknownEventError(event)
        self.push_event("component-echo", {"id": self.id})
        self.send_update(EchoComponent, "right", {"value": f"from-{self.id}"})
        return {"echo": value}

    def render(self):
        return t'<p id="echo-{self.id}" phx-target="{self.myself}">{self.value}</p>'


@live_view("/client-events")
class ClientEventsLive(LiveView):
    connected_page: ClassVar[ClientEventsLive | None] = None

    @classmethod
    def reset(cls) -> None:
        cls.connected_page = None

    async def mount(self, context: MountContext) -> None:
        self.push_event("mounted", {"connected": context.connected})
        if context.connected:
            type(self).connected_page = self

    async def handle_event(
        self, event: str, value: object
    ) -> Mapping[str, object] | None:
        if event == "ping" and isinstance(value, dict):
            count = cast(dict[str, object], value)["n"]
            self.push_event("pinged", {"n": count}, dispatch="before")
            return {"pong": count}
        if event == "silent":
            return None
        if event == "rejected":
            self.push_event("leaked")
            self.send_update(EchoComponent, "left", {"value": "leaked"})
            raise UnknownEventError(event)
        if event == "update":
            self.send_update(EchoComponent, "left", {"value": "updated"})
            self.send_update(EchoComponent, "missing", {"value": "ignored"})
            return None
        if event == "bad_reply":
            return {"value": float("nan")}
        raise UnknownEventError(event)

    async def handle_info(self, name: str, value: object) -> None:
        if name != "notify":
            await super().handle_info(name, value)
            return
        self.push_event("notified", {"value": value})

    def render(self):
        left = self.live_component(EchoComponent, "left", {})
        right = self.live_component(EchoComponent, "right", {})
        return t"<section>{left}{right}</section>"


def _asgi(application: NestApplication) -> ASGIApp:
    return application.get_adapter(StarletteAdapter).app


async def _request(
    application: NestApplication,
    path: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=_asgi(application))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.get(path, headers=headers)


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


def _join(
    token: str, *, ref: str = "1", url: str = "http://testserver/counter"
) -> Message:
    return _receive_text(
        [
            ref,
            ref,
            _TOPIC,
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


def _event(
    ref: str,
    event: str,
    *,
    value: object = None,
    cid: int | None = None,
    event_type: str = "click",
    join_ref: str = "1",
) -> Message:
    payload: dict[str, object] = {
        "type": event_type,
        "event": event,
        "value": {} if value is None else value,
    }
    if cid is not None:
        payload["cid"] = cid
    return _receive_text([join_ref, ref, _TOPIC, "event", payload])


def _reply_payload(frame: list[object]) -> dict[str, object]:
    assert frame[3] == "phx_reply"
    return cast(dict[str, object], frame[4])


def _response(frame: list[object]) -> dict[str, object]:
    payload = _reply_payload(frame)
    return cast(dict[str, object], payload["response"])


class _ChannelSession:
    """Drive one Channel connection a frame at a time."""

    def __init__(self, application: NestApplication) -> None:
        self._application = application
        self._incoming: asyncio.Queue[Message] = asyncio.Queue()
        self._changed = asyncio.Event()
        self._task: asyncio.Future[None] | None = None
        self.sent: list[Message] = []

    async def start(self) -> None:
        await self._incoming.put({"type": "websocket.connect"})

        async def receive() -> Message:
            return await self._incoming.get()

        async def send(message: Message) -> None:
            self.sent.append(message)
            self._changed.set()

        self._task = asyncio.ensure_future(
            _asgi(self._application)(
                _websocket_scope("/_tori/live/websocket"), receive, send
            )
        )

    async def push(self, message: Message) -> None:
        await self._incoming.put(message)

    async def frames(self, count: int) -> list[list[object]]:
        async def wait() -> None:
            while len(_decode_sent(self.sent)) < count:
                self._changed.clear()
                await self._changed.wait()

        await asyncio.wait_for(wait(), timeout=2)
        return _decode_sent(self.sent)

    async def close(self) -> None:
        await self._incoming.put(_disconnect())
        await self.ended()

    async def cancel(self) -> None:
        """Cancel the connection's handling, as a stopping server does."""
        assert self._task is not None
        self._task.cancel()
        await asyncio.wait_for(
            asyncio.gather(self._task, return_exceptions=True), timeout=2
        )

    async def ended(self) -> list[Message]:
        """Wait for the server to finish the connection and return every frame."""
        assert self._task is not None
        await asyncio.wait_for(self._task, timeout=2)
        return self.sent


@pytest.mark.asyncio
async def test_unknown_info_raises_the_public_error() -> None:
    with pytest.raises(UnknownInfoError, match="Unknown LiveView info: tick"):
        await UntitledLive().handle_info("tick", None)


@pytest.mark.asyncio
async def test_send_info_requires_a_connection_and_rejects_a_full_queue() -> None:
    page = UntitledLive()
    assert not page.send_info("tick")

    page._connect_liveview()
    assert all(page.send_info("tick", value) for value in range(32))
    assert not page.send_info("tick", 32)

    await page._disconnect_liveview()
    assert not page.send_info("tick", 33)


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

    unsafe_label = "<unsafe>"
    page.stream_insert(
        "activity-stream",
        "activity-template",
        t'<li id="activity-template">{unsafe_label}</li>',
    )
    assert (
        '<li id="activity-template">&lt;unsafe&gt;</li>'
        in page.stream_contents("activity-stream").value
    )
    page.stream_reset("activity-stream")

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
    assert "const hooks = (globalThis.ToriLiveHooks ??= {});" in client.text
    assert "const source = globalThis.ToriLiveParams;" in client.text
    assert "{hooks, params}," in client.text
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
        _join(token, url="http://testserver/counter?start=2"),
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
    # Unchanged statics stay with the client; only the change and title travel.
    assert _response(messages[1])["diff"] == {"0": "3", "t": "Counter 3"}
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
        _join(_token(page.text), url="http://testserver/form"),
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
async def test_send_info_serializes_with_events_and_closes_on_handler_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ServerUpdatesLive.reset()
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[ServerUpdatesLive],
        key="server-updates",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/server-updates")
    token = _token(page.text)

    incoming: asyncio.Queue[Message] = asyncio.Queue()
    await incoming.put({"type": "websocket.connect"})
    await incoming.put(_join(token, url="http://testserver/server-updates"))
    await incoming.put(_event("2", "increment"))
    sent: list[Message] = []
    server_update_sent = asyncio.Event()
    send_results: list[bool] = []

    async def receive() -> Message:
        return await incoming.get()

    async def send(message: Message) -> None:
        sent.append(message)
        render_messages = _decode_sent(sent)
        if len(render_messages) == 1:
            connected_page = ServerUpdatesLive.connected_page
            assert connected_page is not None
            send_results.append(connected_page.send_info("set", 7))
        elif len(render_messages) == 3:
            server_update_sent.set()

    session = asyncio.ensure_future(
        _asgi(application)(
            _websocket_scope("/_tori/live/websocket"),
            receive,
            send,
        )
    )
    await asyncio.wait_for(ServerUpdatesLive.mounted.wait(), timeout=1)
    connected_page = ServerUpdatesLive.connected_page
    assert connected_page is not None
    await asyncio.wait_for(server_update_sent.wait(), timeout=1)

    messages = _decode_sent(sent)
    snapshot = cast(dict[str, object], _response(messages[0])["rendered"])
    assert send_results == [True]
    assert snapshot == {
        "s": ["<output>", "</output>"],
        "0": "0",
        "t": "",
    }
    assert messages[1] == [
        "1",
        "2",
        _TOPIC,
        "phx_reply",
        {
            "status": "ok",
            "response": {"diff": {"0": "1"}},
        },
    ]
    assert messages[2] == [
        "1",
        None,
        _TOPIC,
        "diff",
        {"0": "7"},
    ]

    with caplog.at_level(logging.ERROR, logger="tori_py_liveview.endpoint"):
        assert connected_page.send_info("unknown", "application-secret")
        await asyncio.wait_for(session, timeout=1)
    assert sent[-1] == {"type": "websocket.close", "code": 1011, "reason": ""}
    assert "info=unknown" in caplog.text
    assert "application-secret" not in caplog.text
    assert not connected_page.send_info("set", 8)
    assert ServerUpdatesLive.disconnect_send_results == [False]
    await application.shutdown()


@pytest.mark.asyncio
async def test_server_updates_that_change_nothing_push_no_diff() -> None:
    ServerUpdatesLive.reset()
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[ServerUpdatesLive],
        key="quiet-updates",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/server-updates")
    session = _ChannelSession(application)
    await session.start()
    await session.push(_join(_token(page.text), url="http://testserver/server-updates"))
    await session.frames(1)
    connected_page = ServerUpdatesLive.connected_page
    assert connected_page is not None

    # Updates are handled in order, so a push for the first would come first.
    assert connected_page.send_info("set", 0)
    assert connected_page.send_info("set", 5)
    frames = await session.frames(2)
    assert frames[1] == ["1", None, _TOPIC, "diff", {"0": "5"}]

    await session.close()
    await application.shutdown()


@pytest.mark.asyncio
async def test_components_keep_state_route_targets_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    CounterComponent.reset()
    forgotten: list[list[int]] = []
    forget = _RenderState.forget

    def record_forget(state: _RenderState, cids: Iterable[int]) -> None:
        cids = list(cids)
        forgotten.append(cids)
        forget(state, cids)

    monkeypatch.setattr(_RenderState, "forget", record_forget)
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
        _join(token, url="http://testserver/components"),
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
    # The second instance of a template copies the first one's statics.
    assert components["2"]["s"] == 1
    assert components["2"]["2"] == "Right"

    # A component event changes only that component.
    assert _response(messages[1])["diff"] == {"c": {"1": {"3": "1"}}}
    assert _response(messages[2])["diff"] == {"c": {"2": {"3": "1"}}}
    assert _reply_payload(messages[3]) == {
        "status": "ok",
        "response": {"reason": "unknown_target"},
    }
    assert _reply_payload(messages[4]) == {
        "status": "ok",
        "response": {"reason": "unknown_event"},
    }
    assert _response(messages[5])["diff"] == {"1": ""}
    assert _response(messages[6]) == {}
    assert _response(messages[7]) == {"cids": [2]}
    # The server forgets the trees the client prunes after this reply.
    assert forgotten == [[2]]
    restored = cast(dict[str, object], _response(messages[8])["diff"])
    assert restored["1"] == 3
    restored_components = cast(dict[str, dict[str, object]], restored["c"])
    # The new component copies the statics of a cached one this render keeps.
    assert restored_components["3"]["s"] == -1
    assert restored_components["3"]["2"] == "Right"
    assert restored_components["3"]["3"] == "0"
    assert CounterComponent.mounts == 5
    assert CounterComponent.mount_connections == [False, False, True, True, True]
    assert CounterComponent.updates == 11
    assert CounterComponent.disconnects == 5
    await application.shutdown()


@pytest.mark.asyncio
async def test_nested_components_update_and_leave_with_their_parent() -> None:
    LeafComponent.disconnects = []
    BranchComponent.disconnects = []
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[NestedLive],
        key="nested",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/nested")
    assert '<li id="leaf-a" phx-click="bump" phx-target="2">A:0</li>' in page.text
    # The disconnected render disconnects its nested components too.
    assert BranchComponent.disconnects == ["tree"]
    assert sorted(LeafComponent.disconnects) == ["a", "b"]
    LeafComponent.disconnects = []
    BranchComponent.disconnects = []
    session = _ChannelSession(application)
    await session.start()
    await session.push(_join(_token(page.text), url="http://testserver/nested"))
    joined = _rendered((await session.frames(1))[0])
    assert joined["0"] == 1
    components = cast(dict[str, dict[str, object]], joined["c"])
    # The branch holds its leaves' CIDs; the second leaf copies the first's statics.
    assert components["1"]["2"] == {"s": ["", "", ""], "0": 2, "1": 3}
    assert components["3"]["s"] == 2

    await session.push(_event("2", "bump", cid=3))
    assert _diff((await session.frames(2))[1]) == {"c": {"3": {"3": "1"}}}

    await session.push(_event("3", "recount"))
    assert _diff((await session.frames(3))[2]) == {"c": {"2": {"3": "5"}}}

    # Dropping a leaf changes only its parent, and the client then destroys it.
    await session.push(_event("4", "drop", cid=1))
    assert _diff((await session.frames(4))[3]) == {
        "c": {"1": {"2": {"s": ["", ""], "0": 2}}}
    }
    await session.push(
        _receive_text(["1", "5", _TOPIC, "cids_will_destroy", {"cids": [3]}])
    )
    await session.push(
        _receive_text(["1", "6", _TOPIC, "cids_destroyed", {"cids": [3]}])
    )
    assert _response((await session.frames(6))[5]) == {"cids": [3]}
    assert LeafComponent.disconnects == ["b"]

    # Removing the branch removes its remaining leaf with it.
    await session.push(_event("7", "toggle"))
    assert _diff((await session.frames(7))[6]) == {"0": ""}
    await session.push(
        _receive_text(["1", "8", _TOPIC, "cids_will_destroy", {"cids": [1, 2]}])
    )
    await session.push(
        _receive_text(["1", "9", _TOPIC, "cids_destroyed", {"cids": [1, 2]}])
    )
    assert _response((await session.frames(9))[8]) == {"cids": [1, 2]}
    assert BranchComponent.disconnects == ["tree"]
    assert LeafComponent.disconnects == ["b", "a"]

    # Brought back, the branch and its leaves mount afresh with new CIDs.
    await session.push(_event("10", "toggle"))
    restored = _diff((await session.frames(10))[9])
    assert restored["0"] == 4
    restored_components = cast(dict[str, dict[str, object]], restored["c"])
    assert set(restored_components) == {"4", "5", "6"}
    assert restored_components["5"]["3"] == "0"

    await session.close()
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
        _join(token, url="http://testserver/streams"),
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
        # Otherwise the server waits for the next join until its idle deadline.
        _disconnect(),
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
        _join(token, url="http://testserver/untitled"),
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

    @live_view("/idle-info")
    class IdleInfoLive(LiveView):
        def __init__(self) -> None:
            self.count = 0
            self.task: asyncio.Task[None] | None = None

        async def mount(self, context: MountContext) -> None:
            if context.connected:
                self.task = asyncio.create_task(self._push_updates())

        async def handle_info(self, name: str, value: object) -> None:
            del value
            if name != "tick":
                await super().handle_info(name, None)
                return
            self.count += 1

        async def disconnect(self) -> None:
            if self.task is None:
                return
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

        def render(self):
            return rendered(("<output>", "</output>"), self.count)

        async def _push_updates(self) -> None:
            while self.send_info("tick"):
                await asyncio.sleep(0.001)

    idle_timeout_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32, idle_timeout_seconds=0.03),
        pages=[IdleInfoLive],
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
    page = await _request(idle_application, "/idle-info")
    token = _token(page.text)
    idle_timeout = await _call_websocket(
        idle_application,
        "/_tori/live/websocket",
        _join(token, url="http://testserver/idle-info"),
    )
    assert idle_timeout[-1]["type"] == "websocket.close"
    assert idle_timeout[-1]["code"] == 1001
    assert len(_decode_sent(idle_timeout)) > 1
    await idle_application.shutdown()


@pytest.mark.asyncio
async def test_slow_event_handler_does_not_consume_idle_timeout() -> None:
    @live_view("/slow-event")
    class SlowEventLive(LiveView):
        async def handle_event(self, event: str, value: object) -> None:
            del value
            if event != "slow":
                raise UnknownEventError(event)
            await asyncio.sleep(0.08)

        def render(self):
            return "<div>slow</div>"

    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32, idle_timeout_seconds=0.03),
        pages=[SlowEventLive],
        key="slow-event",
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    page = await _request(application, "/slow-event")
    token = _token(page.text)
    messages: asyncio.Queue[Message] = asyncio.Queue()
    await messages.put({"type": "websocket.connect"})
    await messages.put(_join(token, url="http://testserver/slow-event"))
    await messages.put(_event("2", "slow"))
    sent: list[Message] = []

    async def receive() -> Message:
        return await messages.get()

    async def send(message: Message) -> None:
        sent.append(message)

    async def continue_session() -> None:
        await asyncio.sleep(0.05)
        await messages.put(_receive_text([None, "3", "phoenix", "heartbeat", {}]))
        await asyncio.sleep(0.01)
        await messages.put(_disconnect())

    continuation = asyncio.create_task(continue_session())
    try:
        await _asgi(application)(
            _websocket_scope("/_tori/live/websocket"), receive, send
        )
    finally:
        await continuation
        await application.shutdown()

    frames = _decode_sent(sent)
    assert _response(frames[1]) == {"diff": {}}
    assert _reply_payload(frames[2]) == {"status": "ok", "response": {}}
    assert [
        message.get("code") for message in sent if message["type"] == "websocket.close"
    ] == [1000]


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
        _join(token, url="http://testserver/crash"),
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
        _join(token, url="http://testserver/component-crash"),
        _event("2", "crash", cid=1),
    )
    assert sent[-1]["type"] == "websocket.close"
    assert sent[-1]["code"] == 1011
    assert CrashingComponent.disconnects == 2
    assert CrashingComponentsLive.disconnects == 1
    await application.shutdown()


async def _client_events_application(key: str) -> NestApplication:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret="s" * 32),
        pages=[ClientEventsLive],
        key=key,
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    return application


@pytest.mark.asyncio
async def test_pushed_events_and_replies_ride_on_phoenix_render_trees() -> None:
    ClientEventsLive.reset()
    application = await _client_events_application("client-events")
    page = await _request(application, "/client-events")
    session = _ChannelSession(application)
    await session.start()

    await session.push(_join(_token(page.text), url="http://testserver/client-events"))
    joined = _response((await session.frames(1))[0])
    snapshot = cast(dict[str, object], joined["rendered"])
    assert snapshot["e"] == [["mounted", {"connected": True}]]
    assert "r" not in snapshot

    await session.push(_event("2", "ping", value={"n": 41}, event_type="hook"))
    ping = cast(dict[str, object], _response((await session.frames(2))[1])["diff"])
    assert ping["r"] == {"pong": 41}
    assert ping["e"] == [["pinged", {"n": 41}, True]]

    await session.push(_event("3", "silent"))
    silent = cast(dict[str, object], _response((await session.frames(3))[2])["diff"])
    assert "r" not in silent
    assert "e" not in silent

    await session.push(_event("4", "rejected"))
    assert _response((await session.frames(4))[3]) == {"reason": "unknown_event"}

    await session.push(_event("5", "update"))
    update = cast(dict[str, object], _response((await session.frames(5))[4])["diff"])
    # Only the updated component travels; its unchanged sibling stays cached.
    assert update == {"c": {"1": {"2": "updated"}}}

    connected_page = ClientEventsLive.connected_page
    assert connected_page is not None
    assert connected_page.send_info("notify", 7)
    pushed = (await session.frames(6))[5]
    assert pushed[:4] == ["1", None, _TOPIC, "diff"]
    assert cast(dict[str, object], pushed[4])["e"] == [["notified", {"value": 7}]]

    await session.push(_event("6", "echo", value={"x": 1}, cid=1))
    echo = cast(dict[str, object], _response((await session.frames(7))[6])["diff"])
    assert echo["r"] == {"echo": {"x": 1}}
    assert echo["e"] == [["component-echo", {"id": "left"}]]
    assert echo["c"] == {"2": {"2": "from-left"}}

    await session.close()
    await application.shutdown()


@pytest.mark.asyncio
async def test_invalid_event_reply_closes_the_connection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = await _client_events_application("invalid-reply")
    page = await _request(application, "/client-events")

    with caplog.at_level(logging.ERROR, logger="tori_py_liveview.endpoint"):
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join(_token(page.text), url="http://testserver/client-events"),
            _event("2", "bad_reply"),
        )
    assert sent[-1] == {"type": "websocket.close", "code": 1011, "reason": ""}
    assert len(_decode_sent(sent)) == 1
    await application.shutdown()


@pytest.mark.asyncio
async def test_push_event_and_send_update_validate_and_reset() -> None:
    page = ClientEventsLive()
    with pytest.raises(TypeError, match="name must be a string"):
        page.push_event(cast(Any, 1))
    with pytest.raises(ValueError, match="cannot be empty"):
        page.push_event("")
    with pytest.raises(ValueError, match="dispatch"):
        page.push_event("x", dispatch=cast(Any, "later"))
    with pytest.raises(TypeError, match="must be a mapping"):
        page.push_event("x", cast(Any, [1]))
    with pytest.raises(TypeError, match="keys must be strings"):
        page.push_event("x", cast(Any, {1: "a"}))
    with pytest.raises(ValueError, match="JSON object"):
        page.push_event("x", {"value": float("inf")})
    with pytest.raises(ValueError, match="JSON object"):
        page.push_event("x", {"value": object()})

    items = [1, 2]
    page.push_event("snapshot", {"items": items})
    items.append(3)
    page.push_event("empty", dispatch="before")
    assert page._take_liveview_events() == [
        ["snapshot", {"items": [1, 2]}],
        ["empty", {}, True],
    ]
    assert page._take_liveview_events() == []

    with pytest.raises(TypeError, match="LiveComponent subclass"):
        page.send_update(cast(Any, object), "left")
    with pytest.raises(TypeError, match="id must be a string"):
        page.send_update(EchoComponent, cast(Any, 1))

    page.push_event("dropped")
    page.send_update(EchoComponent, "left", {"value": "dropped"})
    await page._disconnect_liveview_components()
    assert page._take_liveview_events() == []
    assert page._liveview_component_updates == []

    detached = EchoComponent()
    with pytest.raises(LiveViewError, match="not attached"):
        detached.push_event("x")
    with pytest.raises(LiveViewError, match="not attached"):
        detached.send_update(EchoComponent, "left")


_SECRET = "s" * 32


@live_view("/flash", action="index")
@live_view("/flash/next", action="next")
class FlashLive(LiveView):
    contexts: ClassVar[list[MountContext]] = []
    mounted_flash: ClassVar[list[dict[str, str]]] = []

    @classmethod
    def reset(cls) -> None:
        cls.contexts = []
        cls.mounted_flash = []

    async def mount(self, context: MountContext) -> None:
        type(self).contexts.append(context)
        type(self).mounted_flash.append(dict(self.flash))
        go = context.query_params.get("go")
        if go == "flash":
            self.put_flash("info", "from mount")
        elif go == "redirect":
            self.put_flash("info", "redirected")
            self.redirect("/flash/next")
        elif go == "bounce":
            self.redirect("/flash/next")
        elif go == "bounce-cleared":
            self.clear_flash()
            self.redirect("/flash/next")
        elif go == "hop":
            self.push_navigate("/flash/next")
        elif go == "away":
            self.put_flash("info", "Leaving")
            self.redirect("https://idp.example/login")

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event == "save":
            self.put_flash("info", "Saved")
        elif event == "navigate":
            self.put_flash("info", "Moved")
            self.push_navigate("/flash/next")
        elif event == "leave":
            self.put_flash("info", "Left")
            self.redirect("/elsewhere")
        elif event == "quiet":
            self.push_navigate("/flash/next")
        elif event == "away":
            self.put_flash("info", "Leaving")
            self.redirect("https://idp.example/login")
        elif event == "drop":
            self.put_flash("error", "lost")
            raise UnknownEventError(event)
        else:
            raise UnknownEventError(event)

    def render(self):
        info = self.flash.get("info", "")
        error = self.flash.get("error", "")
        return t"<p>{info}</p><p>{error}</p>"


_GATES: dict[str, asyncio.Event] = {}
_CANCELLED: list[str] = []


def _gated(gate: str, value: object) -> Callable[[], Awaitable[object]]:
    async def run() -> object:
        event = _GATES.setdefault(gate, asyncio.Event())
        try:
            await event.wait()
        except asyncio.CancelledError:
            _CANCELLED.append(gate)
            raise
        if isinstance(value, BaseException):
            raise value
        return value

    return run


def _open_gate(gate: str) -> None:
    _GATES.setdefault(gate, asyncio.Event()).set()


def _immediately(value: object) -> Callable[[], Awaitable[object]]:
    async def run() -> object:
        return value

    return run


async def _until(predicate: Callable[[], bool]) -> None:
    async def wait() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout=2)


class AsyncWidget(LiveComponent):
    def __init__(self) -> None:
        self.value = "waiting"

    def mount(self) -> None:
        self.start_async("widget", _gated("widget", "loaded"))

    async def handle_async(self, name: str, result: AsyncResult[object]) -> None:
        self.value = f"{name}:{result.result}"

    def render(self):
        return t"<span>{self.value}</span>"


class CleanupWidget(LiveComponent):
    events: ClassVar[list[str]] = []

    def mount(self) -> None:
        self.start_async("work", self.work)

    async def work(self) -> object:
        try:
            await asyncio.Event().wait()
        finally:
            type(self).events.append("work stopped")
        return None

    async def disconnect(self) -> None:
        type(self).events.append("component disconnected")

    def render(self) -> str:
        return "<span></span>"


@live_view("/async")
class AsyncLive(LiveView):
    outcomes: ClassVar[list[tuple[str, AsyncResult[object]]]] = []
    cancel_results: ClassVar[list[bool]] = []

    @classmethod
    def reset(cls) -> None:
        cls.outcomes = []
        cls.cancel_results = []
        _GATES.clear()
        _CANCELLED.clear()

    def __init__(self) -> None:
        self.org: AsyncResult[object] = AsyncResult()
        self.status = "idle"

    async def mount(self, context: MountContext) -> None:
        del context
        self.assign_async("org", _gated("org", "Acme"))

    async def handle_event(self, event: str, value: object) -> None:
        gate = cast(dict[str, str], value).get("gate", "job")
        if event == "start":
            self.start_async("job", _gated(gate, "done"))
        elif event == "fail":
            self.start_async("job", _gated(gate, RuntimeError("boom")))
        elif event == "sync":
            self.start_async("job", cast(Any, lambda: 42))
        elif event == "cancel":
            type(self).cancel_results.append(self.cancel_async("job"))
        elif event == "reload":
            self.assign_async("org", _gated(gate, "Beta"))
        elif event == "explode":
            self.start_async("explode", _gated(gate, "x"))
        elif event == "leave":
            self.push_navigate("/flash")
        else:
            raise UnknownEventError(event)

    async def handle_async(self, name: str, result: AsyncResult[object]) -> None:
        if name == "explode":
            raise RuntimeError("handle_async failed")
        type(self).outcomes.append((name, result))
        self.status = "ok" if result.ok else type(result.failed).__name__

    def render(self):
        org = self.org
        if org.loading:
            state = "loading"
        elif org.failed is not None:
            state = "failed"
        else:
            state = "ready" if org.ok else "idle"
        value = org.result if org.ok else ""
        widget = self.live_component(AsyncWidget, "widget")
        return t"<p>{state}</p><p>{value}</p><p>{self.status}</p>{widget}"


@live_view("/gone")
class GoneLive(LiveView):
    status: ClassVar[int] = 404
    disconnects: ClassVar[int] = 0
    # Which connected join step raises: mount, a patch it queues, or render.
    phase: ClassVar[str] = "mount"

    def __init__(self) -> None:
        self.connected = False

    async def mount(self, context: MountContext) -> None:
        self.connected = context.connected
        if not context.connected:
            return
        if type(self).phase == "mount":
            raise HttpException(type(self).status, "gone")
        if type(self).phase == "patch":
            self.push_patch("/gone?step=2")

    async def handle_params(self, params: dict[str, str], uri: str) -> None:
        del uri
        if params.get("step") == "2":
            raise HttpException(type(self).status, "gone")

    async def disconnect(self) -> None:
        type(self).disconnects += 1

    def render(self) -> str:
        if self.connected and type(self).phase == "render":
            raise HttpException(type(self).status, "gone")
        return "<p>gone</p>"


async def _lifecycle_application(key: str) -> NestApplication:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret=_SECRET, redirect_hosts=("idp.example",)),
        pages=[FlashLive, AsyncLive, GoneLive],
        key=key,
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    return application


def _join_with(
    token: str,
    url: str,
    *,
    ref: str = "1",
    params: object = None,
    flash: object = None,
    redirect: bool = False,
) -> Message:
    payload: dict[str, object] = {
        "redirect" if redirect else "url": url,
        "params": {"_mounts": 0} if params is None else params,
        "session": token,
        "static": None,
    }
    if flash is not None:
        payload["flash"] = flash
    return _receive_text([ref, ref, _TOPIC, "phx_join", payload])


def _diff(frame: list[object]) -> dict[str, object]:
    return cast(dict[str, object], _response(frame)["diff"])


def _rendered(frame: list[object]) -> dict[str, object]:
    return cast(dict[str, object], _response(frame)["rendered"])


def _pushed_diff(frame: list[object]) -> dict[str, object]:
    assert frame[1] is None
    assert frame[3] == "diff"
    return cast(dict[str, object], frame[4])


def _component_value_at(diff: dict[str, object], cid: int) -> object:
    components = cast(dict[str, dict[str, object]], diff["c"])
    return components[str(cid)]["0"]


@pytest.mark.asyncio
async def test_flash_validates_reads_and_clears() -> None:
    page = FlashLive()
    assert page.flash == {}
    with pytest.raises(TypeError, match="must be strings"):
        page.put_flash(cast(Any, 1), "x")
    with pytest.raises(TypeError, match="must be strings"):
        page.put_flash("info", cast(Any, None))
    with pytest.raises(ValueError, match="cannot be empty"):
        page.put_flash("", "x")
    with pytest.raises(TypeError, match="must be a string"):
        page.clear_flash(cast(Any, 1))

    page.put_flash("info", "one")
    page.put_flash("error", "two")
    with pytest.raises(TypeError):
        cast(Any, page.flash)["info"] = "mutated"
    page.clear_flash("missing")
    page.clear_flash("error")
    assert page.flash == {"info": "one"}
    assert page._take_liveview_flash_changes() == {"info": "one"}
    assert page._take_liveview_flash_changes() == {}
    page.put_flash("info", "three")
    page.clear_flash()
    assert page.flash == {}
    assert page._take_liveview_flash_changes() == {}

    detached = EchoComponent()
    with pytest.raises(LiveViewError, match="not attached"):
        detached.put_flash("info", "x")
    with pytest.raises(LiveViewError, match="not attached"):
        detached.clear_flash()


@pytest.mark.asyncio
async def test_flash_renders_clears_and_follows_navigation() -> None:
    FlashLive.reset()
    codec = FlashTokenCodec(_SECRET)
    application = await _lifecycle_application("flash")
    page = await _request(application, "/flash?go=flash")
    assert "<p>from mount</p>" in page.text
    assert "set-cookie" not in page.headers
    token = _token(page.text)
    assert MountTokenCodec(_SECRET).verify(token).flash == {"info": "from mount"}

    session = _ChannelSession(application)
    await session.start()
    await session.push(_join_with(token, "http://testserver/flash?go=flash"))
    assert _rendered((await session.frames(1))[0])["0"] == "from mount"
    assert FlashLive.mounted_flash[-1] == {"info": "from mount"}

    await session.push(_event("2", "lv:clear-flash", value={"key": "info"}))
    assert _diff((await session.frames(2))[1])["0"] == ""
    await session.push(_event("3", "save"))
    assert _diff((await session.frames(3))[2])["0"] == "Saved"
    await session.push(_event("4", "lv:clear-flash"))
    assert _diff((await session.frames(4))[3])["0"] == ""
    await session.push(_event("5", "lv:clear-flash", cid=99))
    assert _response((await session.frames(5))[4]) == {"reason": "unknown_target"}

    # A rejected handler's flash stays on the page but does not travel.
    await session.push(_event("6", "drop"))
    assert _response((await session.frames(6))[5]) == {"reason": "unknown_event"}
    await session.push(_event("7", "quiet"))
    assert _response((await session.frames(7))[6]) == {
        "live_redirect": {"kind": "push", "to": "/flash/next"}
    }

    # A live navigation without a flash token never revives the HTTP flash.
    await session.push(
        _join_with(token, "http://testserver/flash/next", ref="8", redirect=True)
    )
    assert _reply_payload((await session.frames(8))[7])["status"] == "ok"
    assert FlashLive.mounted_flash[-1] == {}

    await session.push(_event("9", "navigate", join_ref="8"))
    navigated = _response((await session.frames(9))[8])
    live_redirect = cast(dict[str, object], navigated["live_redirect"])
    assert codec.verify(live_redirect["flash"]) == {"info": "Moved"}

    await session.push(
        _join_with(
            token,
            "http://testserver/flash/next",
            ref="10",
            redirect=True,
            flash=live_redirect["flash"],
        )
    )
    assert _rendered((await session.frames(10))[9])["0"] == "Moved"
    assert FlashLive.mounted_flash[-1] == {"info": "Moved"}

    await session.push(_event("11", "leave", join_ref="10"))
    left = _response((await session.frames(11))[10])
    redirect = cast(dict[str, object], left["redirect"])
    assert redirect["to"] == "/elsewhere"
    assert codec.verify(redirect["flash"]) == {"info": "Left"}
    await session.ended()
    await application.shutdown()


@pytest.mark.asyncio
async def test_flash_reaches_reconnects_only_through_navigation_tokens() -> None:
    FlashLive.reset()
    codec = FlashTokenCodec(_SECRET)
    application = await _lifecycle_application("flash-reconnect")
    token = _token((await _request(application, "/flash?go=flash")).text)

    for params, flash, expected in (
        ({"_mounts": 1}, None, {}),
        ({}, None, {}),
        ({"_mounts": False}, None, {}),
        ({"_mounts": 1}, codec.sign({"info": "carried"}), {"info": "carried"}),
        ({"_mounts": 0}, "forged.token", {}),
    ):
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_with(
                token, "http://testserver/flash?go=flash", params=params, flash=flash
            ),
            _disconnect(),
        )
        assert _reply_payload(_decode_sent(sent)[0])["status"] == "ok"
        assert FlashLive.mounted_flash[-1] == expected
    await application.shutdown()


@pytest.mark.asyncio
async def test_flash_cookie_carries_redirect_flash_into_the_http_render() -> None:
    FlashLive.reset()
    codec = FlashTokenCodec(_SECRET)
    application = await _lifecycle_application("flash-cookie")

    cookie_token = codec.sign({"info": "From cookie"})
    page = await _request(
        application, "/flash", headers={"cookie": f"__phoenix_flash__={cookie_token}"}
    )
    assert "<p>From cookie</p>" in page.text
    assert page.headers["set-cookie"] == (
        "__phoenix_flash__=; Max-Age=0; Path=/; SameSite=Lax"
    )
    assert MountTokenCodec(_SECRET).verify(_token(page.text)).flash == {
        "info": "From cookie"
    }

    forged = await _request(
        application, "/flash", headers={"cookie": "__phoenix_flash__=forged"}
    )
    assert "<p></p>" in forged.text
    assert forged.headers["set-cookie"].startswith("__phoenix_flash__=; Max-Age=0")

    redirected = await _request(application, "/flash?go=redirect")
    assert redirected.status_code == 302
    assert redirected.headers["location"] == "/flash/next"
    match = re.fullmatch(
        r"__phoenix_flash__=([^;]+); Max-Age=60; Path=/; SameSite=Lax",
        redirected.headers["set-cookie"],
    )
    assert match is not None
    assert codec.verify(match[1]) == {"info": "redirected"}
    await application.shutdown()


def _cookie_flash(response: httpx.Response, codec: FlashTokenCodec) -> object:
    match = re.fullmatch(
        r"__phoenix_flash__=([^;]*); Max-Age=(\d+); Path=/; SameSite=Lax",
        response.headers["set-cookie"],
    )
    assert match is not None
    return codec.verify(match[1]) if match[2] == "60" else None


@pytest.mark.asyncio
async def test_flash_stays_behind_when_a_redirect_leaves_the_site() -> None:
    FlashLive.reset()
    codec = FlashTokenCodec(_SECRET)
    application = await _lifecycle_application("flash-off-site")

    # No flash cookie is set for another host, and a received one is removed.
    away = await _request(application, "/flash?go=away")
    assert away.status_code == 302
    assert away.headers["location"] == "https://idp.example/login"
    assert "set-cookie" not in away.headers
    incoming = {"cookie": f"__phoenix_flash__={codec.sign({'info': 'Welcome'})}"}
    away = await _request(application, "/flash?go=away", headers=incoming)
    assert _cookie_flash(away, codec) is None

    token = _token((await _request(application, "/flash")).text)
    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join_with(token, "http://testserver/flash"),
        _event("2", "away"),
    )
    assert _response(_decode_sent(sent)[1]) == {
        "redirect": {"to": "https://idp.example/login"}
    }
    await application.shutdown()


@pytest.mark.asyncio
async def test_flash_passes_through_pages_that_navigate_while_mounting() -> None:
    FlashLive.reset()
    codec = FlashTokenCodec(_SECRET)
    application = await _lifecycle_application("flash-pass-through")
    incoming = {"cookie": f"__phoenix_flash__={codec.sign({'info': 'Welcome'})}"}

    # An HTTP mount that redirects forwards the flash it received, not only
    # flash it put itself, and clearing it first forwards nothing.
    bounced = await _request(application, "/flash?go=bounce", headers=incoming)
    assert bounced.status_code == 302
    assert _cookie_flash(bounced, codec) == {"info": "Welcome"}
    cleared = await _request(application, "/flash?go=bounce-cleared", headers=incoming)
    assert cleared.status_code == 302
    assert _cookie_flash(cleared, codec) is None

    # A connected mount that navigates forwards a navigation's incoming flash.
    token = _token((await _request(application, "/flash")).text)
    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join_with(
            token,
            "http://testserver/flash?go=hop",
            redirect=True,
            flash=codec.sign({"info": "Carried"}),
        ),
        _disconnect(),
    )
    reply = _reply_payload(_decode_sent(sent)[0])
    assert reply["status"] == "error"
    response = cast(dict[str, object], reply["response"])
    live_redirect = cast(dict[str, object], response["live_redirect"])
    assert live_redirect["to"] == "/flash/next"
    assert codec.verify(live_redirect["flash"]) == {"info": "Carried"}
    await application.shutdown()


@pytest.mark.asyncio
async def test_every_leave_after_a_join_error_is_acknowledged() -> None:
    FlashLive.reset()
    application = await _lifecycle_application("repeated-leaves")
    token = _token((await _request(application, "/flash")).text)

    # The official client leaves an errored join twice before joining again.
    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join_with(token, "http://testserver/flash?go=hop", ref="12", redirect=True),
        _receive_text(["12", "13", _TOPIC, "phx_leave", {}]),
        _receive_text(["12", "14", _TOPIC, "phx_leave", {}]),
        _join_with(token, "http://testserver/flash/next", ref="17", redirect=True),
        _disconnect(),
    )
    frames = _decode_sent(sent)
    assert [frame[:4] for frame in frames] == [
        ["12", "12", _TOPIC, "phx_reply"],
        ["12", "13", _TOPIC, "phx_reply"],
        ["12", "14", _TOPIC, "phx_reply"],
        ["17", "17", _TOPIC, "phx_reply"],
    ]
    assert _reply_payload(frames[0])["status"] == "error"
    assert _reply_payload(frames[1]) == {"status": "ok", "response": {}}
    assert _reply_payload(frames[2]) == {"status": "ok", "response": {}}
    assert _reply_payload(frames[3])["status"] == "ok"
    closes = [item["code"] for item in sent if item["type"] == "websocket.close"]
    assert closes == [1000]
    await application.shutdown()


def _heartbeat(ref: str, *, join_ref: str | None = None) -> Message:
    return _receive_text([join_ref, ref, "phoenix", "heartbeat", {}])


@pytest.mark.asyncio
async def test_heartbeats_between_joins_are_acknowledged_but_not_before_the_first() -> (
    None
):
    FlashLive.reset()
    application = await _lifecycle_application("heartbeat-between-joins")
    token = _token((await _request(application, "/flash")).text)
    hop = _join_with(token, "http://testserver/flash?go=hop", ref="12", redirect=True)
    leave = _receive_text(["12", "13", _TOPIC, "phx_leave", {}])
    rejoin = _join_with(token, "http://testserver/flash/next", ref="17", redirect=True)

    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        hop,
        _heartbeat("15"),
        leave,
        _heartbeat("16"),
        rejoin,
        _disconnect(),
    )
    frames = _decode_sent(sent)
    assert [frame[:4] for frame in frames] == [
        ["12", "12", _TOPIC, "phx_reply"],
        [None, "15", "phoenix", "phx_reply"],
        ["12", "13", _TOPIC, "phx_reply"],
        [None, "16", "phoenix", "phx_reply"],
        ["17", "17", _TOPIC, "phx_reply"],
    ]
    assert _reply_payload(frames[1]) == {"status": "ok", "response": {}}
    assert _reply_payload(frames[4])["status"] == "ok"
    assert [item["code"] for item in sent if item["type"] == "websocket.close"] == [
        1000
    ]

    # A heartbeat with a join ref, or any heartbeat before the first join, is
    # still a protocol error.
    for incoming in (
        (hop, _heartbeat("15", join_ref="12")),
        (_heartbeat("1"),),
    ):
        sent = await _call_websocket(application, "/_tori/live/websocket", *incoming)
        assert sent[-1] == {"type": "websocket.close", "code": 1002, "reason": ""}
    await application.shutdown()


@pytest.mark.asyncio
async def test_join_exposes_connect_params_and_tracked_static() -> None:
    FlashLive.reset()
    application = await _lifecycle_application("connect-params")
    token = _token((await _request(application, "/flash")).text)
    params = {
        "_mounts": 0,
        "_mount_attempts": 0,
        "_track_static": ["http://testserver/assets/app-1.css", 7],
        "_live_referer": "http://testserver/elsewhere",
        "locale": "uk",
    }
    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join_with(token, "http://testserver/flash", params=params),
        _disconnect(),
    )
    assert _reply_payload(_decode_sent(sent)[0])["status"] == "ok"

    disconnected, connected = FlashLive.contexts
    assert disconnected.connect_params is None
    assert disconnected.tracked_static == ()
    assert not disconnected.static_changed(["/assets/app-2.css"])
    assert connected.connect_params == params
    with pytest.raises(TypeError):
        cast(Any, connected.connect_params)["locale"] = "en"
    assert connected.tracked_static == ("http://testserver/assets/app-1.css",)
    assert not connected.static_changed(["/assets/app-1.css"])
    assert not connected.static_changed(["http://testserver/assets/app-1.css"])
    assert connected.static_changed(["/assets/app-2.css"])
    assert connected.static_changed([])
    with pytest.raises(TypeError, match="iterable of strings"):
        connected.static_changed("/assets/app-1.css")
    with pytest.raises(TypeError, match="iterable of strings"):
        connected.static_changed([cast(Any, 1)])

    for malformed in (
        _join_with(token, "http://testserver/flash", params=["_mounts"]),
        _join_with(token, "http://testserver/flash", flash=5),
    ):
        sent = await _call_websocket(application, "/_tori/live/websocket", malformed)
        assert sent[-1] == {"type": "websocket.close", "code": 1002, "reason": ""}
    await application.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["patch", "render"])
async def test_client_errors_anywhere_in_the_join_reload_the_page(phase: str) -> None:
    GoneLive.disconnects = 0
    GoneLive.status = 404
    GoneLive.phase = phase
    application = await _lifecycle_application(f"reload-{phase}")
    token = _token((await _request(application, "/gone")).text)
    try:
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_with(token, "http://testserver/gone"),
        )
    finally:
        GoneLive.phase = "mount"
    reply = _reply_payload(_decode_sent(sent)[0])
    response = cast(dict[str, object], reply["response"])
    assert reply["status"] == "error"
    assert (response["reason"], response["status"]) == ("reload", 404)
    identity = f"{GoneLive.__module__}.{GoneLive.__qualname__}"
    assert ReloadTokenCodec(_SECRET).verify(response["token"], identity, "/gone")
    # A normal 1000 close after the handler returns, not a 1011 failure.
    assert [item["code"] for item in sent if item["type"] == "websocket.close"] == [
        1000
    ]
    assert GoneLive.disconnects == 1
    await application.shutdown()


@pytest.mark.asyncio
async def test_connected_mount_client_errors_reload_the_page(
    caplog: pytest.LogCaptureFixture,
) -> None:
    GoneLive.disconnects = 0
    GoneLive.status = 404
    GoneLive.phase = "mount"
    application = await _lifecycle_application("reload")
    token = _token((await _request(application, "/gone")).text)

    sent = await _call_websocket(
        application,
        "/_tori/live/websocket",
        _join_with(token, "http://testserver/gone"),
    )
    reply = _reply_payload(_decode_sent(sent)[0])
    response = cast(dict[str, object], reply["response"])
    reload_token = response.pop("token")
    assert reply == {
        "status": "error",
        "response": {"reason": "reload", "status": 404},
    }
    assert GoneLive.disconnects == 1
    codec = ReloadTokenCodec(_SECRET)
    identity = f"{GoneLive.__module__}.{GoneLive.__qualname__}"
    assert codec.verify(reload_token, identity, "/gone") == 404

    # The reloaded HTTP render answers with the connected mount's error even
    # though its own disconnected mount succeeds, so the browser stops reloading.
    reloaded = await _request(
        application,
        "/gone",
        headers={"cookie": f"__phoenix_reload_status__={reload_token}"},
    )
    assert reloaded.status_code == 404
    assert reloaded.headers["set-cookie"] == (
        "__phoenix_reload_status__=; Max-Age=0; Path=/; SameSite=Lax"
    )
    other_resource = codec.sign(identity, "/gone?page=2", 404)
    for cookie in (other_resource, "forged.token"):
        page = await _request(
            application,
            "/gone",
            headers={"cookie": f"__phoenix_reload_status__={cookie}"},
        )
        assert page.status_code == 200
        assert "set-cookie" not in page.headers

    GoneLive.status = 500
    with caplog.at_level(logging.ERROR, logger="tori_py_liveview.endpoint"):
        sent = await _call_websocket(
            application,
            "/_tori/live/websocket",
            _join_with(token, "http://testserver/gone"),
        )
    assert sent[-1] == {"type": "websocket.close", "code": 1011, "reason": ""}
    assert GoneLive.disconnects == 2
    await application.shutdown()


@pytest.mark.asyncio
async def test_async_results_settle_assigns_and_reach_handle_async() -> None:
    AsyncLive.reset()
    application = await _lifecycle_application("async")
    page = await _request(application, "/async")
    assert "<p>loading</p><p></p><p>idle</p><span>waiting</span>" in page.text
    assert _GATES == {}

    session = _ChannelSession(application)
    await session.start()
    await session.push(_join_with(_token(page.text), "http://testserver/async"))
    assert _rendered((await session.frames(1))[0])["0"] == "loading"

    _open_gate("org")
    settled = _pushed_diff((await session.frames(2))[1])
    assert (settled["0"], settled["1"]) == ("ready", "Acme")
    _open_gate("widget")
    widget = _pushed_diff((await session.frames(3))[2])
    assert _component_value_at(widget, 1) == "widget:loaded"

    # Reloading keeps the previous result while loading.
    await session.push(_event("2", "reload", value={"gate": "org2"}))
    reloading = _diff((await session.frames(4))[3])
    # The kept result is unchanged, so only the loading state travels.
    assert reloading == {"0": "loading"}
    _open_gate("org2")
    reloaded = _pushed_diff((await session.frames(5))[4])
    assert (reloaded["0"], reloaded["1"]) == ("ready", "Beta")

    await session.push(_event("3", "start", value={"gate": "job"}))
    # Starting work changes nothing on the page until its result arrives.
    assert _diff((await session.frames(6))[5]) == {}
    _open_gate("job")
    assert _pushed_diff((await session.frames(7))[6])["2"] == "ok"
    await session.push(_event("4", "fail", value={"gate": "job"}))
    assert _pushed_diff((await session.frames(9))[8])["2"] == "RuntimeError"
    await session.push(_event("5", "sync"))
    assert _pushed_diff((await session.frames(11))[10])["2"] == "TypeError"

    # Restarting a running name cancels it and drops its result.
    await session.push(_event("6", "start", value={"gate": "slow1"}))
    await session.push(_event("7", "start", value={"gate": "slow2"}))
    await session.push(_event("8", "cancel"))
    assert _pushed_diff((await session.frames(15))[14])["2"] == "CancelledError"
    await session.push(_event("9", "cancel"))
    await session.frames(16)
    assert AsyncLive.cancel_results == [True, False]
    assert _CANCELLED == ["slow1", "slow2"]

    outcomes = AsyncLive.outcomes
    assert [name for name, _ in outcomes] == ["job"] * 4
    assert outcomes[0][1] == AsyncResult(ok=True, result="done")
    assert isinstance(outcomes[1][1].failed, RuntimeError)
    assert isinstance(outcomes[2][1].failed, TypeError)
    assert isinstance(outcomes[3][1].failed, asyncio.CancelledError)

    await session.push(_event("10", "start", value={"gate": "slow3"}))
    await session.frames(17)
    await session.close()
    assert _CANCELLED == ["slow1", "slow2", "slow3"]
    assert len(_decode_sent(session.sent)) == 17
    await application.shutdown()


@pytest.mark.asyncio
async def test_failing_handle_async_closes_the_connection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    AsyncLive.reset()
    application = await _lifecycle_application("async-failure")
    page = await _request(application, "/async")
    session = _ChannelSession(application)
    await session.start()
    await session.push(_join_with(_token(page.text), "http://testserver/async"))
    await session.frames(1)
    _open_gate("job")
    with caplog.at_level(logging.ERROR, logger="tori_py_liveview.endpoint"):
        await session.push(_event("2", "explode", value={"gate": "job"}))
        sent = await session.ended()
    assert sent[-1] == {"type": "websocket.close", "code": 1011, "reason": ""}
    assert "LiveView async result failed" in caplog.text
    await application.shutdown()


@pytest.mark.asyncio
async def test_async_validates_and_cancels_component_work() -> None:
    AsyncLive.reset()
    page = AsyncLive()
    work = _gated("unused", "x")
    with pytest.raises(TypeError, match="name must be a string"):
        page.start_async(cast(Any, 1), work)
    with pytest.raises(ValueError, match="cannot be empty"):
        page.start_async("", work)
    with pytest.raises(TypeError, match="callable"):
        page.start_async("job", cast(Any, 1))
    for name in ("_org", "not-public", ""):
        with pytest.raises(ValueError, match="public attribute"):
            page.assign_async(name, work)
    with pytest.raises(TypeError, match="name must be a string"):
        page.assign_async(cast(Any, 1), work)
    with pytest.raises(TypeError, match="name must be a string"):
        page.cancel_async(cast(Any, 1))

    # The disconnected render marks assigns loading but starts nothing.
    page.start_async("job", work)
    page.assign_async("org", work)
    assert page.org == AsyncResult(loading=True)
    assert not page.cancel_async("job")
    assert _GATES == {}
    failure = RuntimeError()
    page.org = AsyncResult(ok=True, result="kept", failed=failure)
    page.assign_async("org", work)
    assert page.org == AsyncResult(loading=True, ok=True, result="kept")
    page.assign_async("org", work, reset=True)
    assert page.org == AsyncResult(loading=True)

    with pytest.raises(UnknownAsyncError, match="Unknown LiveView async result: x"):
        await UntitledLive().handle_async("x", AsyncResult())
    with pytest.raises(UnknownAsyncError):
        await EchoComponent().handle_async("x", AsyncResult())
    detached = AsyncWidget()
    with pytest.raises(LiveViewError, match="not attached"):
        detached.start_async("x", work)
    with pytest.raises(LiveViewError, match="not attached"):
        detached.assign_async("value", work)
    with pytest.raises(LiveViewError, match="not attached"):
        detached.cancel_async("x")

    # Component work is cancelled with the component and never delivered.
    page._connect_liveview()
    widget = AsyncWidget()
    widget._attach_liveview("widget", 1, True, page)
    widget.mount()
    assert widget.cancel_async("missing") is False
    await asyncio.sleep(0)
    await page._disconnect_liveview_component(widget)
    await page._disconnect_liveview()
    assert _CANCELLED == ["widget"]
    assert widget.value == "waiting"


class QueuedResultsLive(LiveView):
    def __init__(self) -> None:
        self.outcomes: list[tuple[str, AsyncResult[object]]] = []

    async def handle_async(self, name: str, result: AsyncResult[object]) -> None:
        self.outcomes.append((name, result))

    def render(self) -> str:
        return "<p></p>"


async def _queued(page: LiveView, count: int) -> None:
    """Wait until finished work has queued ``count`` undelivered completions."""
    queue = page._liveview_info_queue
    assert queue is not None
    await _until(lambda: queue.qsize() == count)


@pytest.mark.asyncio
async def test_finished_work_waiting_in_the_queue_follows_replace_and_cancel() -> None:
    page = QueuedResultsLive()
    page._connect_liveview()

    # Restarting a name drops the old result even after it finished and queued.
    page.start_async("job", _immediately("old"))
    await _queued(page, 1)
    page.start_async("job", _immediately("new"))
    await _queued(page, 2)
    replaced = await page._receive_liveview_info()
    assert isinstance(replaced, _AsyncTask)
    assert await page._settle_liveview_async(replaced) is False
    current = await page._receive_liveview_info()
    assert isinstance(current, _AsyncTask)
    assert await page._settle_liveview_async(current) is True
    assert page.outcomes == [("job", AsyncResult(ok=True, result="new"))]

    # Cancelling work that already finished delivers its real outcome.
    page.start_async("done", _immediately("kept"))
    await _queued(page, 1)
    assert page.cancel_async("done") is True
    finished = await page._receive_liveview_info()
    assert isinstance(finished, _AsyncTask)
    assert await page._settle_liveview_async(finished) is True
    assert page.outcomes[-1] == ("done", AsyncResult(ok=True, result="kept"))
    assert page.cancel_async("done") is False
    await page._disconnect_liveview()


class QuickWidget(LiveComponent):
    delivered: ClassVar[list[object]] = []

    def mount(self) -> None:
        self.start_async("quick", _immediately("done"))

    async def handle_async(self, name: str, result: AsyncResult[object]) -> None:
        type(self).delivered.append(result.result)

    def render(self) -> str:
        return "<span></span>"


class ToggleLive(LiveView):
    def __init__(self) -> None:
        self.show = True

    def render(self):
        widget = self.live_component(QuickWidget, "quick") if self.show else ""
        return t"<div>{widget}</div>"


@pytest.mark.asyncio
async def test_destroyed_component_drops_its_finished_queued_result() -> None:
    QuickWidget.delivered = []
    page = ToggleLive()
    page._connect_liveview()
    await page._render_liveview()
    await _queued(page, 1)

    # The browser confirms the component's removal before the loop reads the
    # queued completion, so the result never reaches the destroyed component.
    page.show = False
    await page._render_liveview()
    page._prepare_liveview_component_destruction([1])
    assert await page._destroy_liveview_components([1]) == [1]
    orphaned = await page._receive_liveview_info()
    assert isinstance(orphaned, _AsyncTask)
    assert await page._settle_liveview_async(orphaned) is False
    assert QuickWidget.delivered == []
    await page._disconnect_liveview()


@pytest.mark.asyncio
async def test_live_navigation_cancels_the_outgoing_pages_work() -> None:
    AsyncLive.reset()
    application = await _lifecycle_application("async-navigation")
    page = await _request(application, "/async")
    session = _ChannelSession(application)
    await session.start()
    await session.push(_join_with(_token(page.text), "http://testserver/async"))
    await session.frames(1)
    await session.push(_event("2", "start", value={"gate": "slow"}))
    await session.frames(2)

    await session.push(_event("3", "leave"))
    assert _response((await session.frames(3))[2]) == {
        "live_redirect": {"kind": "push", "to": "/flash"}
    }
    # Page, assign_async, and component work all stop before the next join.
    await _until(lambda: len(_CANCELLED) == 3)
    assert sorted(_CANCELLED) == ["org", "slow", "widget"]
    assert len(_decode_sent(session.sent)) == 3
    await session.close()
    assert AsyncLive.outcomes == []
    await application.shutdown()


class ReportWidget(LiveComponent):
    report: AsyncResult[object] = AsyncResult()

    def render(self) -> str:
        return "<span></span>"


def test_assign_async_never_shadows_page_or_component_api() -> None:
    page = AsyncLive()
    work = _gated("unused", "x")
    for name in ("title", "flash", "render", "live_action", "send_info", "outcomes"):
        with pytest.raises(ValueError, match=f"{name!r} shadows a class attribute"):
            page.assign_async(name, work)
    assert page.title() is None
    assert page.flash == {}

    widget = ReportWidget()
    widget._attach_liveview("report", 1, False, page)
    for name in ("id", "myself", "connected", "render", "handle_async"):
        with pytest.raises(ValueError, match="shadows a class attribute"):
            widget.assign_async(name, work)
    assert widget.id == "report"

    # Instance attributes and class-level AsyncResult defaults remain targets.
    page.assign_async("org", work)
    assert page.org == AsyncResult(loading=True)
    widget.assign_async("report", work)
    assert widget.report == AsyncResult(loading=True)
    assert ReportWidget.report == AsyncResult()


@pytest.mark.asyncio
async def test_removed_component_work_stops_before_its_disconnect_hook() -> None:
    CleanupWidget.events = []
    page = AsyncLive()
    page._connect_liveview()
    widget = CleanupWidget()
    widget._attach_liveview("cleanup", 1, True, page)
    widget.mount()
    await asyncio.sleep(0)

    await page._disconnect_liveview_component(widget)
    assert CleanupWidget.events == ["work stopped", "component disconnected"]
    await page._disconnect_liveview()


@pytest.mark.asyncio
async def test_cancelled_async_work_is_awaited_only_until_the_cancel_deadline(
    caplog: pytest.LogCaptureFixture,
) -> None:
    release = asyncio.Event()

    async def stubborn() -> object:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
        return None

    page = AsyncLive()
    page._connect_liveview(async_cancel_timeout=0.05)
    page.start_async("stubborn", stubborn)
    (task,) = page._liveview_async_running
    await asyncio.sleep(0)

    # Disconnect returns at the deadline even though the work ignores cancel.
    with caplog.at_level(logging.WARNING, logger="tori_py_liveview.page"):
        await asyncio.wait_for(page._disconnect_liveview(), timeout=2)
    assert not task.done()
    assert (
        "LiveView async work ignored cancellation for 0.05s: "
        "tori-py-liveview async stubborn"
    ) in caplog.text

    release.set()
    await task


class CounterChildLive(LiveView):
    events: ClassVar[list[str]] = []
    connected: ClassVar[dict[str, CounterChildLive]] = {}

    def __init__(self) -> None:
        self.label = ""
        self.count = 0
        self.nested = False

    @classmethod
    def reset(cls) -> None:
        cls.events = []
        cls.connected = {}

    async def mount(self, context: MountContext) -> None:
        self.label = context.params.get("label", "")
        self.nested = context.params.get("nested") == "yes"
        type(self).events.append(
            f"mount:{self.label}:{context.connected}:{context.resource}"
        )
        if not context.connected:
            return
        type(self).connected[self.label] = self
        if context.params.get("gone") == "yes":
            raise HttpException(404, "gone")
        if context.params.get("away") == "yes":
            self.push_navigate("/children-other")

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event == "bump":
            self.count += 1
        elif event == "away":
            self.put_flash("info", "Away")
            self.push_navigate("/children-other")
        elif event == "leave":
            self.redirect("/children-other")
        else:
            raise UnknownEventError(event)

    async def handle_info(self, name: str, value: object) -> None:
        if name != "set":
            await super().handle_info(name, value)
            return
        self.count = cast(int, value)

    def title(self) -> str | None:
        return "Child" if self.label == "titled" else None

    def render(self):
        inner = (
            self.live_render(
                CounterChildLive, f"{self.label}-inner", {"label": "inner"}
            )
            if self.nested
            else ""
        )
        return t"<p>{self.label}:{self.count}</p>{inner}"

    async def disconnect(self) -> None:
        type(self).events.append(f"disconnect:{self.label}")


@live_view("/children")
class ParentLive(LiveView):
    def __init__(self) -> None:
        self.show = True
        self.count = 0
        self.child_params = {"label": "a"}

    async def mount(self, context: MountContext) -> None:
        for key in ("label", "nested", "gone", "away"):
            value = context.query_params.get(key)
            if value is not None:
                self.child_params[key] = value

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event == "toggle":
            self.show = not self.show
        elif event == "bump":
            self.count += 1
        else:
            raise UnknownEventError(event)

    def render(self):
        child = (
            self.live_render(CounterChildLive, "counter", self.child_params)
            if self.show
            else ""
        )
        return t"<main><b>{self.count}</b>{child}</main>"


@live_view("/children-other")
class OtherChildrenLive(LiveView):
    def render(self) -> str:
        return "<p>other</p>"


async def _children_application(key: str) -> NestApplication:
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret=_SECRET),
        pages=[ParentLive, OtherChildrenLive],
        embedded=[CounterChildLive],
        key=key,
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    return application


def _child_session(markup: object, view_id: str) -> str:
    match = re.search(rf'<div id="{view_id}" data-phx-session="([^"]+)"', str(markup))
    assert match is not None
    return match[1]


def _child_join(view_id: str, token: str, ref: str) -> Message:
    payload = {"params": {"_mounts": 0}, "session": token, "static": ""}
    return _receive_text([ref, ref, f"lv:{view_id}", "phx_join", payload])


def _child_message(
    view_id: str, join_ref: str, ref: str, event: str, payload: dict[str, object]
) -> Message:
    return _receive_text([join_ref, ref, f"lv:{view_id}", event, payload])


def _child_event(view_id: str, join_ref: str, ref: str, event: str) -> Message:
    payload: dict[str, object] = {"type": "click", "event": event, "value": {}}
    return _child_message(view_id, join_ref, ref, "event", payload)


async def _joined_parent(
    application: NestApplication, path: str = "/children"
) -> tuple[_ChannelSession, dict[str, object]]:
    page = await _request(application, path)
    session = _ChannelSession(application)
    await session.start()
    await session.push(_join(_token(page.text), url=f"http://testserver{path}"))
    return session, _rendered((await session.frames(1))[0])


@pytest.mark.asyncio
async def test_http_render_includes_child_views_and_their_children() -> None:
    CounterChildLive.reset()
    application = await _children_application("children-http")
    page = await _request(application, "/children?nested=yes")
    assert '<main><b>0</b><div id="counter" data-phx-session="' in page.text
    assert (
        'data-phx-static="" data-phx-parent-id="tori-live-root"><p>a:0</p>'
        '<div id="a-inner" data-phx-session="'
    ) in page.text
    assert (
        'data-phx-parent-id="counter"><p>inner:0</p></div></div></main>'
    ) in page.text
    # Children mount with their params and the page's resource, and like the
    # page itself they do not disconnect after the HTTP render.
    assert CounterChildLive.events == [
        "mount:a:False:/children?nested=yes",
        "mount:inner:False:/children?nested=yes",
    ]
    await application.shutdown()


@pytest.mark.asyncio
async def test_child_views_join_and_update_on_their_own_topic() -> None:
    CounterChildLive.reset()
    application = await _children_application("children-join")
    session, root = await _joined_parent(application)
    container = root["1"]
    assert isinstance(container, str)
    assert container.endswith('data-phx-parent-id="tori-live-root"></div>')

    await session.push(
        _child_join("counter", _child_session(container, "counter"), "10")
    )
    joined = (await session.frames(2))[1]
    assert joined[:4] == ["10", "10", "lv:counter", "phx_reply"]
    # A child without a title leaves the page title alone.
    assert _response(joined) == {
        "rendered": {"s": ["<p>", ":", "</p>", ""], "0": "a", "1": "0", "2": ""},
        "liveview_version": "1.2.11",
    }
    assert CounterChildLive.events[-1] == "mount:a:True:/children"

    await session.push(_child_event("counter", "10", "11", "bump"))
    assert _response((await session.frames(3))[2]) == {"diff": {"1": "1"}}
    # The parent renders around the joined child, whose container stays put.
    await session.push(_event("2", "bump"))
    assert _diff((await session.frames(4))[3]) == {"0": "1"}
    assert CounterChildLive.connected["a"].send_info("set", 7)
    assert (await session.frames(5))[4] == [
        "10",
        None,
        "lv:counter",
        "diff",
        {"1": "7"},
    ]

    # The client leaves a removed child, which disconnects; Phoenix answers
    # later messages for its topic as unmatched.
    await session.push(_event("3", "toggle"))
    assert _diff((await session.frames(6))[5]) == {"1": ""}
    await session.push(_child_message("counter", "10", "12", "phx_leave", {}))
    assert _reply_payload((await session.frames(7))[6]) == {
        "status": "ok",
        "response": {},
    }
    await _until(lambda: CounterChildLive.events[-1] == "disconnect:a")
    await session.push(_child_event("counter", "10", "13", "bump"))
    assert _reply_payload((await session.frames(8))[7]) == {
        "status": "error",
        "response": {"reason": "unmatched topic"},
    }
    await session.push(_event("4", "bump"))
    assert _diff((await session.frames(9))[8]) == {"0": "2"}

    # Rendered again, the child gets a fresh token and joins with it afresh.
    await session.push(_event("5", "toggle"))
    restored = _diff((await session.frames(10))[9])["1"]
    token = _child_session(restored, "counter")
    assert token != _child_session(container, "counter")
    await session.push(_child_join("counter", token, "14"))
    assert _reply_payload((await session.frames(11))[10])["status"] == "ok"
    assert CounterChildLive.events[-1] == "mount:a:True:/children"
    await session.close()
    await application.shutdown()


@pytest.mark.asyncio
async def test_child_views_join_only_under_a_joined_parent_with_their_own_token() -> (
    None
):
    CounterChildLive.reset()
    application = await _children_application("children-auth")
    page = await _request(application, "/children?nested=yes")
    session = _ChannelSession(application)
    await session.start()
    await session.push(
        _join(_token(page.text), url="http://testserver/children?nested=yes")
    )
    root = _rendered((await session.frames(1))[0])
    child_token = _child_session(root["1"], "counter")
    inner_token = _child_session(page.text, "a-inner")

    unauthorized = {"status": "error", "response": {"reason": "unauthorized"}}
    # Another view's token, the page's mount token, and a grandchild whose
    # parent has not joined are all refused.
    await session.push(_child_join("other", child_token, "20"))
    await session.push(_child_join("counter", _token(page.text), "21"))
    await session.push(_child_join("a-inner", inner_token, "22"))
    frames = await session.frames(4)
    assert [_reply_payload(frame) for frame in frames[1:4]] == [unauthorized] * 3

    await session.push(_child_join("counter", child_token, "23"))
    joined = _response((await session.frames(5))[4])
    rendered = cast(dict[str, object], joined["rendered"])
    await session.push(
        _child_join("a-inner", _child_session(rendered["2"], "a-inner"), "24")
    )
    assert _reply_payload((await session.frames(6))[5])["status"] == "ok"

    # Leaving the main view closes its children, grandchildren first.
    await session.push(_receive_text(["1", "2", _TOPIC, "phx_leave", {}]))
    await session.frames(7)
    await _until(
        lambda: CounterChildLive.events[-2:] == ["disconnect:inner", "disconnect:a"]
    )
    # Their own leaves may still follow, and are acknowledged between joins.
    await session.push(_child_message("a-inner", "24", "25", "phx_leave", {}))
    await session.push(_child_message("counter", "23", "26", "phx_leave", {}))
    frames = await session.frames(9)
    assert [_reply_payload(frame)["status"] for frame in frames[7:9]] == ["ok", "ok"]

    # A second join of a joined child's topic breaks the protocol.
    await session.push(
        _join(_token(page.text), ref="3", url="http://testserver/children?nested=yes")
    )
    root = _rendered((await session.frames(10))[9])
    token = _child_session(root["1"], "counter")
    await session.push(_child_join("counter", token, "30"))
    await session.frames(11)
    await session.push(_child_join("counter", token, "31"))
    sent = await session.ended()
    assert [m.get("code") for m in sent if m["type"] == "websocket.close"] == [1002]
    await application.shutdown()


@pytest.mark.asyncio
async def test_child_tokens_join_only_under_the_mount_that_rendered_them() -> None:
    CounterChildLive.reset()
    application = await _children_application("children-mount-binding")
    unauthorized = {"status": "error", "response": {"reason": "unauthorized"}}
    page = await _request(application, "/children?label=old-root")
    url = "http://testserver/children?label=old-root"

    session = _ChannelSession(application)
    await session.start()
    await session.push(_join(_token(page.text), url=url))
    root = _rendered((await session.frames(1))[0])
    token = _child_session(root["1"], "counter")
    # The official client joins children with the tokens of their parent's
    # connected render, so the HTTP render's tokens are refused.
    await session.push(
        _child_join("counter", _child_session(page.text, "counter"), "10")
    )
    assert _reply_payload((await session.frames(2))[1]) == unauthorized
    await session.push(_child_join("counter", token, "11"))
    assert _reply_payload((await session.frames(3))[2])["status"] == "ok"
    await session.close()

    # A reconnect mounts the page afresh, and the old mount's tokens no longer
    # join, nor do they under another page of the same live session.
    other = await _request(application, "/children-other")
    for join in (
        _join(_token(page.text), url=url),
        _join(_token(other.text), url="http://testserver/children-other"),
    ):
        session = _ChannelSession(application)
        await session.start()
        await session.push(join)
        await session.frames(1)
        await session.push(_child_join("counter", token, "10"))
        assert _reply_payload((await session.frames(2))[1]) == unauthorized
        await session.close()
    await application.shutdown()


@pytest.mark.asyncio
async def test_a_page_reached_by_live_navigation_renders_joinable_children() -> None:
    CounterChildLive.reset()
    application = await _children_application("children-navigation-binding")
    other = await _request(application, "/children-other")
    session = _ChannelSession(application)
    await session.start()
    await session.push(
        _join_with(_token(other.text), "http://testserver/children", redirect=True)
    )
    root = _rendered((await session.frames(1))[0])
    await session.push(
        _child_join("counter", _child_session(root["1"], "counter"), "10")
    )
    assert _reply_payload((await session.frames(2))[1])["status"] == "ok"
    await session.close()
    await application.shutdown()


@pytest.mark.asyncio
async def test_a_leaving_child_closes_its_own_children() -> None:
    CounterChildLive.reset()
    application = await _children_application("children-nested-leave")
    session, root = await _joined_parent(application, "/children?nested=yes")
    await session.push(
        _child_join("counter", _child_session(root["1"], "counter"), "10")
    )
    joined = _response((await session.frames(2))[1])
    rendered = cast(dict[str, object], joined["rendered"])
    await session.push(
        _child_join("a-inner", _child_session(rendered["2"], "a-inner"), "11")
    )
    await session.frames(3)

    await session.push(_child_message("counter", "10", "12", "phx_leave", {}))
    await session.frames(4)
    await _until(
        lambda: CounterChildLive.events[-2:] == ["disconnect:inner", "disconnect:a"]
    )
    await session.push(_child_event("a-inner", "11", "13", "bump"))
    assert _reply_payload((await session.frames(5))[4])["response"] == {
        "reason": "unmatched topic"
    }
    await session.close()
    await application.shutdown()


@pytest.mark.asyncio
async def test_a_rejoined_child_refuses_the_tokens_of_its_earlier_mount() -> None:
    CounterChildLive.reset()
    application = await _children_application("children-rejoin")
    unauthorized = {"status": "error", "response": {"reason": "unauthorized"}}
    session, root = await _joined_parent(application, "/children?nested=yes")
    token = _child_session(root["1"], "counter")
    await session.push(_child_join("counter", token, "10"))
    first = cast(dict[str, object], _response((await session.frames(2))[1])["rendered"])
    earlier = _child_session(first["2"], "a-inner")
    await session.push(_child_message("counter", "10", "11", "phx_leave", {}))
    await session.frames(3)

    # Joining the child again with the same token mounts it afresh, so only the
    # tokens its new mount renders join its own children.
    await session.push(_child_join("counter", token, "12"))
    second = cast(
        dict[str, object], _response((await session.frames(4))[3])["rendered"]
    )
    await session.push(_child_join("a-inner", earlier, "13"))
    assert _reply_payload((await session.frames(5))[4]) == unauthorized
    await session.push(
        _child_join("a-inner", _child_session(second["2"], "a-inner"), "14")
    )
    assert _reply_payload((await session.frames(6))[5])["status"] == "ok"
    await session.close()
    await application.shutdown()


@pytest.mark.asyncio
async def test_child_views_navigate_the_page_and_close() -> None:
    CounterChildLive.reset()
    application = await _children_application("children-navigate")
    session, root = await _joined_parent(application)
    token = _child_session(root["1"], "counter")
    await session.push(_child_join("counter", token, "10"))
    await session.frames(2)

    await session.push(_child_event("counter", "10", "11", "away"))
    navigated = _reply_payload((await session.frames(3))[2])
    live_redirect = cast(
        dict[str, object],
        cast(dict[str, object], navigated["response"])["live_redirect"],
    )
    assert (live_redirect["kind"], live_redirect["to"]) == ("push", "/children-other")
    assert FlashTokenCodec(_SECRET).verify(live_redirect["flash"]) == {"info": "Away"}
    await _until(lambda: CounterChildLive.events[-1] == "disconnect:a")
    # The main view stays until the client replaces it.
    await session.push(_event("2", "bump"))
    assert _diff((await session.frames(4))[3]) == {"0": "1"}

    await session.push(_child_join("counter", token, "12"))
    await session.frames(5)
    await session.push(_child_event("counter", "12", "13", "leave"))
    redirected = _reply_payload((await session.frames(6))[5])
    assert redirected == {
        "status": "ok",
        "response": {"redirect": {"to": "/children-other"}},
    }
    await session.ended()
    await application.shutdown()


@pytest.mark.asyncio
async def test_child_mounts_can_navigate_or_reload_the_page() -> None:
    CounterChildLive.reset()
    application = await _children_application("children-mount")
    session, root = await _joined_parent(application, "/children?away=yes")
    await session.push(
        _child_join("counter", _child_session(root["1"], "counter"), "10")
    )
    navigated = _reply_payload((await session.frames(2))[1])
    assert navigated == {
        "status": "error",
        "response": {"live_redirect": {"kind": "push", "to": "/children-other"}},
    }
    assert CounterChildLive.events[-1] == "disconnect:a"
    await session.close()

    session, root = await _joined_parent(application, "/children?gone=yes")
    await session.push(
        _child_join("counter", _child_session(root["1"], "counter"), "10")
    )
    reload = cast(
        dict[str, object], _reply_payload((await session.frames(2))[1])["response"]
    )
    assert (reload["reason"], reload["status"]) == ("reload", 404)
    # The reload token names the main page, whose HTTP render then answers 404.
    assert (
        ReloadTokenCodec(_SECRET).verify(
            reload["token"],
            f"{ParentLive.__module__}.{ParentLive.__qualname__}",
            "/children?gone=yes",
        )
        == 404
    )
    await session.close()
    await application.shutdown()


@pytest.mark.asyncio
async def test_a_child_that_sets_a_title_sends_it() -> None:
    CounterChildLive.reset()
    application = await _children_application("children-title")
    session, root = await _joined_parent(application, "/children?label=titled")
    await session.push(
        _child_join("counter", _child_session(root["1"], "counter"), "10")
    )
    rendered = cast(
        dict[str, object], _response((await session.frames(2))[1])["rendered"]
    )
    assert rendered["t"] == "Child"
    await session.close()
    await application.shutdown()


class ScopeStamp:
    """A request-scoped value that tells one work scope from another."""

    issued = 0

    def __init__(self) -> None:
        type(self).issued += 1
        self.value = type(self).issued


class ScopeStampInterceptor:
    def __init__(self, stamp: Annotated[ScopeStamp, Inject(ScopeStamp)]) -> None:
        self.stamp = stamp

    async def intercept(
        self,
        context: MethodInvocationContext,
        next: Callable[[], Awaitable[object]],
    ) -> object:
        del context
        await next()
        return self.stamp.value


class ScopeProbe:
    @use_method_interceptors("scope-stamp")
    async def active_scope(self) -> object:
        return None


@module(
    providers=[
        ClassProvider(ScopeStamp, scope=Scope.REQUEST),
        ClassProvider("scope-stamp", ScopeStampInterceptor, scope=Scope.REQUEST),
        ClassProvider(ScopeProbe, proxy=True),
    ],
    exports=[ScopeStamp, ScopeProbe],
)
class ScopeProbeModule:
    pass


class _ScopeCheckingLive(LiveView):
    checks: ClassVar[list[tuple[str, int, object]]] = []
    pages: ClassVar[dict[str, _ScopeCheckingLive]] = {}
    waiting: ClassVar[asyncio.Event] = asyncio.Event()

    def __init__(
        self,
        stamp: Annotated[ScopeStamp, Inject(ScopeStamp)],
        probe: Annotated[ScopeProbe, Inject(ScopeProbe)],
    ) -> None:
        self.stamp = stamp
        self.probe = probe
        self.label = "page"
        self.show = True

    @classmethod
    def reset(cls) -> None:
        _ScopeCheckingLive.checks = []
        _ScopeCheckingLive.pages = {}
        _ScopeCheckingLive.waiting = asyncio.Event()

    async def check(self, phase: str) -> None:
        # The interceptor reports the scope active while this view runs.
        active = await self.probe.active_scope()
        _ScopeCheckingLive.checks.append(
            (f"{self.label}:{phase}", self.stamp.value, active)
        )

    async def mount(self, context: MountContext) -> None:
        self.label = context.params.get("label", "page")
        if context.connected:
            _ScopeCheckingLive.pages[self.label] = self
            await self.check("mount")

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event == "toggle":
            self.show = not self.show
        elif event == "check":
            await self.check("event")
        elif event == "wait":
            _ScopeCheckingLive.waiting.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await self.check("cancelled")
                raise
        else:
            raise UnknownEventError(event)

    async def handle_info(self, name: str, value: object) -> None:
        if name != "check":
            await super().handle_info(name, value)
            return
        await self.check("info")

    async def disconnect(self) -> None:
        await self.check("disconnect")


class ScopedChildLive(_ScopeCheckingLive):
    def render(self):
        inner = (
            self.live_render(ScopedChildLive, "inner", {"label": "inner"})
            if self.label == "a"
            else ""
        )
        return t"<p>{self.label}{inner}</p>"


@live_view("/scoped-children")
class ScopedParentLive(_ScopeCheckingLive):
    def render(self):
        if not self.show:
            return t"<main></main>"
        a = self.live_render(ScopedChildLive, "a", {"label": "a"})
        b = self.live_render(ScopedChildLive, "b", {"label": "b"})
        return t"<main>{a}{b}</main>"


async def _scoped_children_application(key: str) -> NestApplication:
    _ScopeCheckingLive.reset()
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret=_SECRET),
        pages=[ScopedParentLive],
        embedded=[ScopedChildLive],
        imports=[ScopeProbeModule],
        key=key,
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    return application


@pytest.mark.asyncio
async def test_every_view_runs_in_its_own_work_scope() -> None:
    application = await _scoped_children_application("children-scopes")
    session, root = await _joined_parent(application, "/scoped-children")
    await session.push(_event("2", "check"))
    await session.frames(2)
    await session.push(_child_join("a", _child_session(root["0"], "a"), "10"))
    await session.frames(3)
    await session.push(_event("3", "check"))
    await session.frames(4)
    await session.push(_child_join("b", _child_session(root["1"], "b"), "11"))
    await session.frames(5)
    await session.push(_child_event("a", "10", "12", "check"))
    await session.frames(6)
    await session.push(_child_event("b", "11", "13", "check"))
    await session.frames(7)
    assert _ScopeCheckingLive.pages["a"].send_info("check", None)
    await _until(lambda: _ScopeCheckingLive.checks[-1][0] == "a:info")
    # The page drops both children, and the client leaves them.
    await session.push(_event("4", "toggle"))
    await session.frames(8)
    await session.push(_child_message("a", "10", "14", "phx_leave", {}))
    await session.frames(9)
    await session.push(_child_message("b", "11", "15", "phx_leave", {}))
    await session.frames(10)
    await _until(lambda: _ScopeCheckingLive.checks[-1][0] == "b:disconnect")
    await session.push(_event("5", "check"))
    assert _reply_payload((await session.frames(11))[10])["status"] == "ok"
    await session.close()

    checks = _ScopeCheckingLive.checks
    assert [phase for phase, _, _ in checks] == [
        "page:mount",
        "page:event",
        "a:mount",
        "page:event",
        "b:mount",
        "a:event",
        "b:event",
        "a:info",
        "a:disconnect",
        "b:disconnect",
        "page:event",
        "page:disconnect",
    ]
    # Each view's scoped interceptors see the scope its page was resolved in,
    # before, while, and after other views run beside it.
    assert [own for _, own, _ in checks] == [active for _, _, active in checks]
    assert len({own for _, own, _ in checks}) == 3
    await application.shutdown()


@pytest.mark.asyncio
async def test_a_cancelled_connection_stops_its_busy_child_views() -> None:
    application = await _scoped_children_application("children-cancel")
    session, root = await _joined_parent(application, "/scoped-children")
    await session.push(_child_join("a", _child_session(root["0"], "a"), "10"))
    joined = cast(
        dict[str, object], _response((await session.frames(2))[1])["rendered"]
    )
    await session.push(_child_join("inner", _child_session(joined["1"], "inner"), "11"))
    await session.frames(3)
    await session.push(_child_event("a", "10", "12", "wait"))
    await asyncio.wait_for(_ScopeCheckingLive.waiting.wait(), timeout=2)

    # Cancelling the connection also cancels the child's running handler, and
    # every view still disconnects and closes its scope after its children.
    await session.cancel()
    checks = _ScopeCheckingLive.checks
    assert [phase for phase, _, _ in checks] == [
        "page:mount",
        "a:mount",
        "inner:mount",
        "a:cancelled",
        "inner:disconnect",
        "a:disconnect",
        "page:disconnect",
    ]
    assert [own for _, own, _ in checks] == [active for _, _, active in checks]
    await application.shutdown()


class ViewResource:
    """A request-scoped resource whose exit fails for chosen views."""

    exits: ClassVar[list[str]] = []
    failing: ClassVar[set[str]] = set()

    def __init__(self) -> None:
        self.label = ""

    async def __aenter__(self) -> ViewResource:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if not self.label:
            return
        ViewResource.exits.append(self.label)
        if self.label in ViewResource.failing:
            raise RuntimeError(f"{self.label} resource failed")


@module(
    providers=[ClassProvider(ViewResource, scope=Scope.REQUEST)],
    exports=[ViewResource],
)
class ViewResourceModule:
    pass


class _ResourceLive(LiveView):
    disconnects: ClassVar[list[str]] = []

    def __init__(self, resource: Annotated[ViewResource, Inject(ViewResource)]) -> None:
        self.resource = resource
        self.label = "page"
        self.nested = False

    async def mount(self, context: MountContext) -> None:
        self.label = context.params.get("label", "page")
        self.nested = context.params.get("nested") == "yes"
        if context.connected:
            self.resource.label = self.label

    async def disconnect(self) -> None:
        _ResourceLive.disconnects.append(self.label)


class ResourceChildLive(_ResourceLive):
    def render(self):
        if not self.nested:
            return t"<p>{self.label}</p>"
        one = self.live_render(ResourceChildLive, f"{self.label}-1", {"label": "a-1"})
        two = self.live_render(ResourceChildLive, f"{self.label}-2", {"label": "a-2"})
        return t"<p>{self.label}{one}{two}</p>"


@live_view("/resource-children")
class ResourceParentLive(_ResourceLive):
    def render(self):
        a = self.live_render(ResourceChildLive, "a", {"label": "a", "nested": "yes"})
        b = self.live_render(ResourceChildLive, "b", {"label": "b"})
        return t"<main>{a}{b}</main>"


async def _resource_children_application(
    key: str, failing: set[str]
) -> NestApplication:
    _ResourceLive.disconnects = []
    ViewResource.exits = []
    ViewResource.failing = failing
    liveview_module = LiveViewModule.for_root(
        LiveViewOptions(secret=_SECRET),
        pages=[ResourceParentLive],
        embedded=[ResourceChildLive],
        imports=[ViewResourceModule],
        key=key,
    )

    @module(imports=[liveview_module])
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    await application.start()
    return application


@pytest.mark.asyncio
async def test_failing_child_cleanup_still_closes_every_other_view(
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = await _resource_children_application("children-cleanup", {"a", "b"})
    session, root = await _joined_parent(application, "/resource-children")
    await session.push(_child_join("a", _child_session(root["0"], "a"), "10"))
    await session.frames(2)
    await session.push(_child_join("b", _child_session(root["1"], "b"), "11"))
    await session.frames(3)

    with caplog.at_level(logging.ERROR, logger="tori_py_liveview.endpoint"):
        await session.close()
    # Both children fail to close their scopes, yet every view still
    # disconnects and exits its resources, and each failure is logged.
    assert sorted(_ResourceLive.disconnects) == ["a", "b", "page"]
    assert sorted(ViewResource.exits) == ["a", "b", "page"]
    assert "LiveView child cleanup failed" in caplog.text
    assert "LiveView scope cleanup failed" in caplog.text
    await application.shutdown()


@pytest.mark.asyncio
async def test_a_leaving_child_closes_all_its_children_despite_failures() -> None:
    application = await _resource_children_application(
        "children-nested-cleanup", {"a-1"}
    )
    session, root = await _joined_parent(application, "/resource-children")
    await session.push(_child_join("a", _child_session(root["0"], "a"), "10"))
    rendered = cast(
        dict[str, object], _response((await session.frames(2))[1])["rendered"]
    )
    await session.push(_child_join("a-1", _child_session(rendered["1"], "a-1"), "11"))
    await session.frames(3)
    await session.push(_child_join("a-2", _child_session(rendered["2"], "a-2"), "12"))
    await session.frames(4)

    # Leaving the child closes both of its children before itself, though the
    # first one fails, and the failure then closes the connection.
    await session.push(_child_message("a", "10", "13", "phx_leave", {}))
    sent = await session.ended()
    assert sent[-1]["type"] == "websocket.close"
    assert sent[-1]["code"] == 1011
    assert _ResourceLive.disconnects == ["a-1", "a-2", "a", "page"]
    assert sorted(ViewResource.exits) == ["a", "a-1", "a-2", "page"]
    await application.shutdown()


@pytest.mark.asyncio
async def test_a_child_task_ends_only_when_the_gateway_closes_it() -> None:
    events: list[str] = []

    class TaskPage(LiveView):
        async def disconnect(self) -> None:
            events.append("disconnect")

        def render(self) -> str:
            return ""

    class Resolver:
        async def resolve(self, token: object) -> object:
            del token
            return TaskPage()

    class TaskScope:
        async def __aenter__(self) -> Resolver:
            return Resolver()

        async def __aexit__(self, *exc_info: object) -> None:
            events.append("scope exit")

    class Scopes:
        def open(self) -> TaskScope:
            return TaskScope()

    async def settle() -> None:
        for _ in range(5):
            await asyncio.sleep(0)

    async def opened() -> _ChildTask:
        child = _ChildTask()
        await child.open(cast(Any, Scopes()), TaskPage)
        return child

    started = asyncio.Event()

    async def wait_forever() -> None:
        started.set()
        await asyncio.Event().wait()

    ran: list[str] = []

    async def record() -> None:
        ran.append("ran")

    # Cancelled while idle, as a shutting down application cancels the tasks of
    # open scopes, a child serves no more calls but keeps its page and scope
    # until the gateway closes it, after its own children.
    idle = await opened()
    idle._task.cancel()
    await settle()
    assert events == []
    with pytest.raises(LiveViewError, match="ended"):
        await idle.call(record)
    await asyncio.wait_for(idle.close(), timeout=2)
    assert events == ["disconnect", "scope exit"]

    # Cancelled while running a call, it cancels the call and waits the same
    # way; cancelled again, as when the event loop shuts down, it ends at once.
    events.clear()
    busy = await opened()
    running = asyncio.create_task(busy.call(wait_forever))
    await asyncio.wait_for(started.wait(), timeout=2)
    busy._task.cancel()
    with pytest.raises(LiveViewError, match="cancelled"):
        await asyncio.wait_for(running, timeout=2)
    await settle()
    assert events == []
    busy._task.cancel()
    await settle()
    assert events == ["disconnect", "scope exit"]
    await asyncio.wait_for(busy.close(), timeout=2)

    # A call whose caller stopped waiting before it started never runs.
    events.clear()
    abandoning = await opened()
    abandoned = asyncio.create_task(abandoning.call(record))
    await asyncio.sleep(0)
    abandoned.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(abandoned, timeout=2)
    await settle()
    await asyncio.wait_for(abandoning.close(), timeout=2)
    assert ran == []
    assert events == ["disconnect", "scope exit"]


def test_embedded_pages_are_registered_without_routes() -> None:
    options = LiveViewOptions(secret=_SECRET)
    with pytest.raises(LiveViewConfigurationError, match="must not declare @live_view"):
        LiveViewModule.for_root(
            options, pages=[ParentLive], embedded=[OtherChildrenLive]
        )
    with pytest.raises(LiveViewConfigurationError, match="LiveView subclasses"):
        LiveViewModule.for_root(
            options, pages=[ParentLive], embedded=[cast(Any, object)]
        )
    with pytest.raises(LiveViewConfigurationError, match="unique"):
        LiveViewModule.for_root(
            options, pages=[ParentLive], embedded=[CounterChildLive, CounterChildLive]
        )
    with pytest.raises(LiveViewConfigurationError, match="iterable"):
        LiveViewModule.for_root(options, pages=[ParentLive], embedded=cast(Any, 1))


def test_child_signer_accepts_only_registered_pages() -> None:
    sign = _child_signer(
        ChildTokenCodec(_SECRET),
        {"pages.Counter": CounterChildLive},
        parent_id="tori-live-root",
        parent_nonce="render-1",
        resource="/children",
        session="",
    )
    token = ChildTokenCodec(_SECRET).verify(sign(CounterChildLive, "counter", {}))
    assert (token.page, token.view_id, token.parent_id, token.parent_nonce) == (
        "pages.Counter",
        "counter",
        "tori-live-root",
        "render-1",
    )
    with pytest.raises(LiveViewError, match="not registered"):
        sign(OtherChildrenLive, "other", {})
