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
    LiveView,
    LiveViewConfigurationError,
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
