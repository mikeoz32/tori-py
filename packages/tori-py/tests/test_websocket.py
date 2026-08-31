from __future__ import annotations

import asyncio
import inspect
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError
from typing import Annotated, Any, cast

import pytest
from starlette.types import ASGIApp, Message
from starlette.websockets import WebSocket
from tori_py import (
    ApplicationOptions,
    Body,
    BootstrapError,
    ClassProvider,
    Context,
    Cookie,
    FactoryProvider,
    Header,
    Inject,
    ModuleId,
    Path,
    PipelineOptions,
    PipelineResult,
    Query,
    Scope,
    ScopeClosedError,
    Socket,
    ValueProvider,
    compile_graph,
    controller,
    get,
    module,
    use_filters,
    use_guard,
    use_guards,
    use_interceptors,
    use_middleware,
    use_pipes,
    websocket_gateway,
)
from tori_py.http import current_http_context
from tori_py.starlette import StarletteAdapter
from tori_py.starlette import asgi as starlette_asgi
from tori_py.testing import TestingModule
from tori_py.websocket import (
    WebSocketContext,
    compile_websocket_gateway,
    compile_websocket_routes,
    current_websocket_context,
)


class NativeSocket:
    pass


def _asgi(application) -> ASGIApp:
    return application.get_adapter(StarletteAdapter).app


def _websocket_scope(
    path: str,
    *,
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Any:
    return {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.5"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query_string,
        "headers": [] if headers is None else headers,
        "client": ("test", 1),
        "server": ("test", 80),
        "subprotocols": [],
    }


async def _call_websocket(
    app: ASGIApp,
    path: str,
    *incoming: Message,
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
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

    await app(
        _websocket_scope(
            path,
            query_string=query_string,
            headers=headers,
        ),
        receive,
        send,
    )
    return sent


def test_websocket_gateway_metadata_is_direct_and_immutable() -> None:
    @websocket_gateway("events")
    class Gateway:
        async def handle(
            self,
            socket: Annotated[NativeSocket, Socket()],
        ) -> None:
            del socket

    metadata = Gateway.__dict__["__tori_py_websocket_gateway_metadata__"]
    assert metadata.path == "events"
    with pytest.raises(FrozenInstanceError):
        metadata.path = "/other"

    with pytest.raises(BootstrapError) as duplicate:
        websocket_gateway("/other")(Gateway)
    assert duplicate.value.diagnostic_code == "gateway.duplicate_metadata"

    with pytest.raises(BootstrapError) as invalid_path:
        websocket_gateway(cast(str, None))
    assert invalid_path.value.diagnostic_code == "gateway.invalid_declaration"


@pytest.mark.asyncio
async def test_gateway_provider_shorthand_compiles_an_immutable_plan() -> None:
    @websocket_gateway("events/{room}")
    class Gateway:
        async def handle(
            self,
            socket: Annotated[NativeSocket, Socket()],
            context: Annotated[WebSocketContext, Context()],
            room: Annotated[str, Path("room")],
            query: Annotated[str, Query("q")] = "all",
            header: Annotated[str, Header("x-test")] = "none",
            cookie: Annotated[str, Cookie("session")] = "none",
            service: Annotated[object, Inject("service")] = None,
        ) -> None:
            del socket, context, room, query, header, cookie, service

    @module(providers=[Gateway])
    class Root:
        pass

    graph = await compile_graph(Root)
    plans = compile_websocket_routes(graph)

    assert len(plans) == 1
    plan = plans[0]
    assert plan.module_id == ModuleId(Root)
    assert plan.gateway is Gateway
    assert plan.path == "/events/{room}"
    assert plan.route_id == "WS /events/{room}"
    assert plan.return_annotation is type(None)
    assert [parameter.kind for parameter in plan.parameters] == [
        "socket",
        "context",
        "path",
        "query",
        "header",
        "cookie",
        "inject",
    ]
    assert plan.parameters[3].has_default is True
    assert plan.parameters[3].default == "all"
    assert graph.providers[plan.gateway_ref].scope is Scope.SINGLETON
    with pytest.raises(FrozenInstanceError):
        cast(Any, plan).path = "/other"


def test_gateway_pipeline_metadata_is_frozen_into_the_plan() -> None:
    class GatewayGuard:
        async def can_activate(self, context) -> bool:
            del context
            return True

    class HandlerGuard:
        async def can_activate(self, context) -> bool:
            del context
            return True

    @websocket_gateway("/events")
    @use_guards(GatewayGuard)
    class Gateway:
        @use_guards(HandlerGuard)
        async def handle(
            self,
            socket: Annotated[NativeSocket, Socket()],
        ) -> None:
            del socket

    plan = compile_websocket_gateway(
        ModuleId(object),
        Gateway,
    )

    assert plan.gateway_pipeline.guards == (GatewayGuard,)
    assert plan.handler_pipeline.guards == (HandlerGuard,)


@pytest.mark.asyncio
async def test_websocket_paths_are_exactly_deduplicated_across_modules() -> None:
    @websocket_gateway("/events")
    class FirstGateway:
        async def handle(
            self,
            socket: Annotated[NativeSocket, Socket()],
        ) -> None:
            del socket

    @websocket_gateway("events")
    class DuplicateGateway:
        async def handle(
            self,
            socket: Annotated[NativeSocket, Socket()],
        ) -> None:
            del socket

    @module(providers=[FirstGateway, DuplicateGateway])
    class Root:
        pass

    graph = await compile_graph(Root)
    with pytest.raises(BootstrapError) as duplicate:
        compile_websocket_routes(graph)
    assert duplicate.value.diagnostic_code == "gateway.duplicate"


@pytest.mark.asyncio
async def test_non_identical_websocket_paths_remain_distinct() -> None:
    @websocket_gateway("/events/{room}")
    class DynamicGateway:
        async def handle(
            self,
            socket: Annotated[NativeSocket, Socket()],
        ) -> None:
            del socket

    @websocket_gateway("/events/main")
    class StaticGateway:
        async def handle(
            self,
            socket: Annotated[NativeSocket, Socket()],
        ) -> None:
            del socket

    @module(providers=[DynamicGateway, StaticGateway])
    class Root:
        pass

    graph = await compile_graph(Root)

    assert tuple(plan.path for plan in compile_websocket_routes(graph)) == (
        "/events/{room}",
        "/events/main",
    )


@pytest.mark.parametrize(
    ("gateway_factory", "code"),
    [
        (
            lambda: websocket_gateway("/events")(type("MissingHandler", (), {})),
            "gateway.invalid_signature",
        ),
        (
            lambda: websocket_gateway("/events")(
                type("SyncHandler", (), {"handle": lambda self: None})
            ),
            "gateway.invalid_signature",
        ),
    ],
)
def test_gateway_requires_one_direct_async_handler(gateway_factory, code: str) -> None:
    gateway = gateway_factory()
    with pytest.raises(BootstrapError) as invalid:
        compile_websocket_gateway(ModuleId(object), gateway)
    assert invalid.value.diagnostic_code == code


def test_gateway_requires_exactly_one_socket_binding() -> None:
    @websocket_gateway("/missing")
    class MissingSocket:
        async def handle(
            self,
            dependency: Annotated[object, Inject("dependency")],
        ) -> None:
            del dependency

    @websocket_gateway("/duplicate")
    class DuplicateSocket:
        async def handle(
            self,
            first: Annotated[NativeSocket, Socket()],
            second: Annotated[NativeSocket, Socket()],
        ) -> None:
            del first, second

    for gateway in (MissingSocket, DuplicateSocket):
        with pytest.raises(BootstrapError) as invalid:
            compile_websocket_gateway(ModuleId(object), gateway)
        assert invalid.value.diagnostic_code == "gateway.invalid_binding"


@pytest.mark.asyncio
async def test_gateway_must_be_singleton() -> None:
    @websocket_gateway("/events")
    class Gateway:
        async def handle(
            self,
            socket: Annotated[NativeSocket, Socket()],
        ) -> None:
            del socket

    @module(
        providers=[ClassProvider(Gateway, Gateway, scope=Scope.REQUEST)],
    )
    class Root:
        pass

    graph = await compile_graph(Root)
    with pytest.raises(BootstrapError) as invalid:
        compile_websocket_routes(graph)
    assert invalid.value.diagnostic_code == "gateway.invalid_declaration"


def test_gateway_signature_is_compiled_without_runtime_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @websocket_gateway("/events")
    class Gateway:
        async def handle(
            self,
            socket: Annotated[NativeSocket, Socket()],
        ) -> None:
            del socket

    plan = compile_websocket_gateway(ModuleId(object), Gateway)

    monkeypatch.setattr(
        inspect,
        "signature",
        lambda target: (_ for _ in ()).throw(AssertionError(target)),
    )
    assert plan.parameters[0].kind == "socket"


@pytest.mark.asyncio
async def test_starlette_gateway_binds_native_handshake_and_connection_scope() -> None:
    events: list[object] = []

    class Session:
        pass

    @asynccontextmanager
    async def session_factory():
        session = Session()
        events.append("session-open")
        try:
            yield session
        finally:
            events.append("session-close")

    @websocket_gateway("/events/{room}")
    class Gateway:
        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
            context: Annotated[WebSocketContext, Context()],
            room: Annotated[str, Path("room")],
            query: Annotated[str, Query("q")],
            header: Annotated[str, Header("x-test")],
            cookie: Annotated[str, Cookie("session")],
            first: Annotated[object, Inject("session")],
            second: Annotated[object, Inject("session")],
        ) -> None:
            path_params = cast(dict[str, object], context.metadata["path_params"])
            with pytest.raises(TypeError):
                path_params["room"] = "changed"
            events.extend(
                [
                    isinstance(socket, WebSocket),
                    context.execution_kind,
                    current_websocket_context() is context,
                    current_http_context() is None,
                    room,
                    query,
                    header,
                    cookie,
                    first is second,
                ]
            )
            await socket.accept()
            await socket.send_text(await socket.receive_text())
            await socket.close()

    @module(
        providers=[
            Gateway,
            FactoryProvider("session", session_factory, scope=Scope.REQUEST),
        ]
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    sent = await _call_websocket(
        _asgi(application),
        "/events/main",
        {"type": "websocket.receive", "text": "hello"},
        query_string=b"q=active",
        headers=[
            (b"x-test", b"header"),
            (b"cookie", b"session=cookie"),
        ],
    )

    assert sent == [
        {"type": "websocket.accept", "subprotocol": None, "headers": []},
        {"type": "websocket.send", "text": "hello"},
        {"type": "websocket.close", "code": 1000, "reason": ""},
    ]
    assert events == [
        "session-open",
        True,
        "websocket",
        True,
        True,
        "main",
        "active",
        "header",
        "cookie",
        True,
        "session-close",
    ]
    assert current_websocket_context() is None
    await application.close()


@pytest.mark.asyncio
async def test_starlette_binary_echo_and_unmatched_route() -> None:
    @websocket_gateway("/binary")
    class Gateway:
        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
        ) -> None:
            await socket.accept()
            await socket.send_bytes(await socket.receive_bytes())
            await socket.close()

    @module(providers=[Gateway])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())

    echoed = await _call_websocket(
        _asgi(application),
        "/binary",
        {"type": "websocket.receive", "bytes": b"payload"},
    )
    unmatched = await _call_websocket(_asgi(application), "/missing")

    assert echoed == [
        {"type": "websocket.accept", "subprotocol": None, "headers": []},
        {"type": "websocket.send", "bytes": b"payload"},
        {"type": "websocket.close", "code": 1000, "reason": ""},
    ]
    assert unmatched == [{"type": "websocket.close", "code": 1000, "reason": ""}]
    await application.close()


@pytest.mark.asyncio
async def test_http_and_websocket_routes_coexist(call_http) -> None:
    @controller("/health")
    class HealthController:
        @get()
        async def health(self) -> dict[str, str]:
            return {"status": "ok"}

    @websocket_gateway("/events")
    class Gateway:
        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
        ) -> None:
            await socket.close()

    @module(controllers=[HealthController], providers=[Gateway])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())

    http_messages = await call_http(_asgi(application), path="/health")
    websocket_messages = await _call_websocket(_asgi(application), "/events")

    assert http_messages[0]["status"] == 200
    assert websocket_messages == [
        {"type": "websocket.close", "code": 1000, "reason": ""}
    ]
    await application.close()


@pytest.mark.asyncio
async def test_websocket_guard_denies_before_handshake_acceptance() -> None:
    events: list[str] = []

    class DenyGuard:
        async def can_activate(self, context) -> bool:
            events.append(context.execution_kind)
            return False

    @websocket_gateway("/guarded")
    @use_guard(DenyGuard())
    class Gateway:
        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
        ) -> None:
            events.append("handler")
            await socket.accept()

    @module(providers=[Gateway])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    sent = await _call_websocket(_asgi(application), "/guarded")

    assert sent == [{"type": "websocket.close", "code": 1008, "reason": ""}]
    assert events == ["websocket"]
    await application.close()


@pytest.mark.asyncio
async def test_websocket_guard_denial_bypasses_exception_filters() -> None:
    events: list[str] = []

    class DenyGuard:
        async def can_activate(self, context) -> bool:
            del context
            return False

    class CatchAllFilter:
        async def catch(self, error, context) -> PipelineResult:
            del error, context
            events.append("filter")
            return PipelineResult.from_value(None)

    @websocket_gateway("/guard-filter")
    @use_guard(DenyGuard())
    @use_filters(CatchAllFilter())
    class Gateway:
        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
        ) -> None:
            await socket.accept()

    @module(providers=[Gateway])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    sent = await _call_websocket(_asgi(application), "/guard-filter")

    assert sent == [{"type": "websocket.close", "code": 1008, "reason": ""}]
    assert events == []
    await application.close()


@pytest.mark.asyncio
async def test_gateway_is_bound_once_at_startup() -> None:
    constructed = 0

    @websocket_gateway("/bound")
    class Gateway:
        def __init__(self) -> None:
            nonlocal constructed
            constructed += 1

        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
        ) -> None:
            await socket.close()

    @module(providers=[Gateway])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    assert constructed == 1
    await _call_websocket(_asgi(application), "/bound")
    await _call_websocket(_asgi(application), "/bound")
    assert constructed == 1
    await application.close()


@pytest.mark.asyncio
async def test_starlette_rejects_an_incompatible_socket_annotation() -> None:
    @websocket_gateway("/invalid")
    class Gateway:
        async def handle(
            self,
            socket: Annotated[NativeSocket, Socket()],
        ) -> None:
            del socket

    @module(providers=[Gateway])
    class Root:
        pass

    with pytest.raises(BootstrapError) as invalid:
        await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    assert invalid.value.diagnostic_code == "gateway.invalid_binding"


@pytest.mark.asyncio
async def test_websocket_pipeline_wraps_the_connection_in_documented_order() -> None:
    events: list[str] = []

    class Middleware:
        def __init__(self, name: str) -> None:
            self.name = name

        async def handle(self, context, next):
            del context
            events.append(f"{self.name}-in")
            result = await next()
            events.append(f"{self.name}-out")
            return result

    class Guard:
        def __init__(self, name: str) -> None:
            self.name = name

        async def can_activate(self, context) -> bool:
            del context
            events.append(self.name)
            return True

    class Pipe:
        def __init__(self, name: str) -> None:
            self.name = name

        async def transform(self, value, metadata):
            events.append(f"{self.name}:{metadata.binding_kind}")
            return f"{value}-{self.name}"

    class Interceptor:
        def __init__(self, name: str) -> None:
            self.name = name

        async def intercept(self, context, next):
            del context
            events.append(f"{self.name}-in")
            result = await next()
            events.append(f"{self.name}-out")
            return result

    @websocket_gateway("/pipeline/{value}")
    @use_middleware("gateway-middleware")
    @use_guards(Guard("gateway-guard"))
    @use_pipes(Pipe("gateway-pipe"))
    @use_interceptors(Interceptor("gateway-interceptor"))
    class Gateway:
        @use_middleware("handler-middleware")
        @use_guards(Guard("handler-guard"))
        @use_pipes(Pipe("handler-pipe"))
        @use_interceptors(Interceptor("handler-interceptor"))
        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
            value: Annotated[str, Path("value")],
        ) -> None:
            events.append(f"handler:{value}")
            await socket.close()

    @module(
        providers=[
            Gateway,
            ValueProvider("global-middleware", Middleware("global-middleware")),
            ValueProvider("gateway-middleware", Middleware("gateway-middleware")),
            ValueProvider("handler-middleware", Middleware("handler-middleware")),
        ]
    )
    class Root:
        pass

    pipeline = PipelineOptions(
        middleware=("global-middleware",),
        guards=(Guard("global-guard"),),
        pipes=(Pipe("global-pipe"),),
        interceptors=(Interceptor("global-interceptor"),),
    )
    application = await TestingModule.create(Root).compile(
        adapter=StarletteAdapter(),
        pipeline=pipeline,
    )
    sent = await _call_websocket(_asgi(application), "/pipeline/raw")

    assert sent == [{"type": "websocket.close", "code": 1000, "reason": ""}]
    assert events == [
        "global-middleware-in",
        "gateway-middleware-in",
        "handler-middleware-in",
        "global-guard",
        "gateway-guard",
        "handler-guard",
        "global-pipe:path",
        "gateway-pipe:path",
        "handler-pipe:path",
        "global-interceptor-in",
        "gateway-interceptor-in",
        "handler-interceptor-in",
        "handler:raw-global-pipe-gateway-pipe-handler-pipe",
        "handler-interceptor-out",
        "gateway-interceptor-out",
        "global-interceptor-out",
        "handler-middleware-out",
        "gateway-middleware-out",
        "global-middleware-out",
    ]
    await application.close()


@pytest.mark.asyncio
async def test_websocket_disconnect_bypasses_filters_and_closes_scope() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def connection_resource():
        events.append("open")
        try:
            yield object()
        finally:
            events.append("close")

    class CatchAllFilter:
        async def catch(self, error, context) -> PipelineResult:
            del error, context
            events.append("filter")
            return PipelineResult.from_value(None)

    @websocket_gateway("/disconnect")
    class Gateway:
        @use_filters(CatchAllFilter())
        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
            resource: Annotated[object, Inject("connection-resource")],
        ) -> None:
            del resource
            await socket.accept()
            await socket.receive_text()

    @module(
        providers=[
            Gateway,
            FactoryProvider(
                "connection-resource",
                connection_resource,
                scope=Scope.REQUEST,
            ),
        ]
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    sent = await _call_websocket(
        _asgi(application),
        "/disconnect",
        {"type": "websocket.disconnect", "code": 1001, "reason": "away"},
    )

    assert sent == [{"type": "websocket.accept", "subprotocol": None, "headers": []}]
    assert events == ["open", "close"]
    assert current_websocket_context() is None
    await application.close()


@pytest.mark.asyncio
async def test_handled_websocket_failure_closes_an_open_connection() -> None:
    class CatchAllFilter:
        async def catch(self, error, context) -> PipelineResult:
            del error, context
            return PipelineResult.from_value(None)

    @websocket_gateway("/handled")
    class Gateway:
        @use_filters(CatchAllFilter())
        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
        ) -> None:
            await socket.accept()
            raise ValueError("handled")

    @module(providers=[Gateway])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    sent = await _call_websocket(_asgi(application), "/handled")

    assert sent == [
        {"type": "websocket.accept", "subprotocol": None, "headers": []},
        {"type": "websocket.close", "code": 1000, "reason": ""},
    ]
    await application.close()


@pytest.mark.asyncio
async def test_handler_oserror_can_be_handled_by_a_filter() -> None:
    events: list[str] = []

    class CatchAllFilter:
        async def catch(self, error, context) -> PipelineResult:
            del context
            events.append(type(error).__name__)
            return PipelineResult.from_value(None)

    @websocket_gateway("/oserror")
    class Gateway:
        @use_filters(CatchAllFilter())
        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
        ) -> None:
            del socket
            raise OSError("application failure")

    @module(providers=[Gateway])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    sent = await _call_websocket(_asgi(application), "/oserror")

    assert events == ["OSError"]
    assert sent == [{"type": "websocket.close", "code": 1000, "reason": ""}]
    await application.close()


@pytest.mark.asyncio
async def test_disconnected_send_oserror_bypasses_filters() -> None:
    events: list[str] = []

    class CatchAllFilter:
        async def catch(self, error, context) -> PipelineResult:
            del error, context
            events.append("filter")
            return PipelineResult.from_value(None)

    @websocket_gateway("/send-failure")
    class Gateway:
        @use_filters(CatchAllFilter())
        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
        ) -> None:
            await socket.accept()

    @module(providers=[Gateway])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    messages: asyncio.Queue[Message] = asyncio.Queue()
    await messages.put({"type": "websocket.connect"})

    async def receive() -> Message:
        return await messages.get()

    async def disconnected_send(message: Message) -> None:
        del message
        raise OSError("connection closed")

    await _asgi(application)(
        _websocket_scope("/send-failure"),
        receive,
        disconnected_send,
    )

    assert events == []
    await application.close()


@pytest.mark.asyncio
async def test_websocket_context_resolver_expires_after_connection() -> None:
    retained = []

    @websocket_gateway("/resolver")
    class Gateway:
        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
            context: Annotated[WebSocketContext, Context()],
        ) -> None:
            retained.append(context.resolver)
            await socket.close()

    @module(providers=[Gateway])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    await _call_websocket(_asgi(application), "/resolver")

    with pytest.raises(ScopeClosedError):
        await retained[0].resolve(Gateway)
    await application.close()


@pytest.mark.asyncio
async def test_invalid_websocket_request_id_is_not_used_for_correlation() -> None:
    request_ids: list[str | None] = []

    @websocket_gateway("/request-id")
    class Gateway:
        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
            context: Annotated[WebSocketContext, Context()],
        ) -> None:
            request_ids.append(context.request_id)
            await socket.close()

    @module(providers=[Gateway])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    await _call_websocket(
        _asgi(application),
        "/request-id",
        headers=[(b"x-request-id", b"unsafe\nvalue")],
    )

    assert request_ids[0] != "unsafe\nvalue"
    assert request_ids[0] is not None
    assert len(request_ids[0]) == 36
    await application.close()


def test_gateway_rejects_http_body_and_inherited_handlers() -> None:
    @websocket_gateway("/body")
    class BodyGateway:
        async def handle(
            self,
            socket: Annotated[NativeSocket, Socket()],
            body: Annotated[object, Body()],
        ) -> None:
            del socket, body

    class BaseGateway:
        async def handle(
            self,
            socket: Annotated[NativeSocket, Socket()],
        ) -> None:
            del socket

    @websocket_gateway("/inherited")
    class InheritedGateway(BaseGateway):
        pass

    with pytest.raises(BootstrapError) as invalid_body:
        compile_websocket_gateway(ModuleId(object), BodyGateway)
    assert invalid_body.value.diagnostic_code == "gateway.invalid_binding"

    with pytest.raises(BootstrapError) as inherited:
        compile_websocket_gateway(ModuleId(object), InheritedGateway)
    assert inherited.value.diagnostic_code == "gateway.invalid_signature"


@pytest.mark.asyncio
async def test_asgi_wrapper_closes_websocket_before_readiness() -> None:
    async def create_application():
        raise AssertionError("factory must not run before lifespan startup")

    app = starlette_asgi(create_application)
    sent = await _call_websocket(cast(ASGIApp, app), "/events")

    assert sent == [{"type": "websocket.close", "code": 1013, "reason": ""}]


@pytest.mark.asyncio
async def test_shutdown_cancels_active_websocket_and_cleans_its_scope() -> None:
    started = asyncio.Event()
    never = asyncio.Event()
    events: list[str] = []

    @asynccontextmanager
    async def connection_resource():
        events.append("open")
        try:
            yield object()
        finally:
            events.append("close")

    @websocket_gateway("/active")
    class Gateway:
        async def handle(
            self,
            socket: Annotated[WebSocket, Socket()],
            resource: Annotated[object, Inject("connection-resource")],
        ) -> None:
            del resource
            await socket.accept()
            started.set()
            await never.wait()

    @module(
        providers=[
            Gateway,
            FactoryProvider(
                "connection-resource",
                connection_resource,
                scope=Scope.REQUEST,
            ),
        ]
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile(
        adapter=StarletteAdapter(),
        options=ApplicationOptions(
            shutdown_timeout=0.2,
            cancellation_grace=0.05,
            cleanup_reserve=0.05,
        ),
    )
    incoming: asyncio.Queue[Message] = asyncio.Queue()
    sent: list[Message] = []
    await incoming.put({"type": "websocket.connect"})

    async def receive() -> Message:
        return await incoming.get()

    async def send(message: Message) -> None:
        sent.append(message)

    connection = asyncio.ensure_future(
        _asgi(application)(
            _websocket_scope("/active"),
            receive,
            send,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    await application.close()
    connection_result = await asyncio.gather(connection, return_exceptions=True)

    assert isinstance(connection_result[0], asyncio.CancelledError)
    assert sent == [{"type": "websocket.accept", "subprotocol": None, "headers": []}]
    assert events == ["open", "close"]
    assert current_websocket_context() is None
