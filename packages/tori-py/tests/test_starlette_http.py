import asyncio
import inspect
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, cast

import pytest
import tori_py.http.routes as routes_module
from starlette.background import BackgroundTask
from starlette.responses import Response
from starlette.types import ASGIApp, Message
from tori_py import (
    Body,
    BootstrapError,
    Context,
    Cookie,
    FactoryProvider,
    Header,
    Inject,
    ModuleId,
    NestApplication,
    Path,
    Query,
    Scope,
    controller,
    get,
    header,
    module,
    no_body,
    post,
    use_guard,
    use_interceptor,
    use_pipe,
)
from tori_py.core.runtime import ApplicationState, RequestScope
from tori_py.http import HttpContext, HttpResponse, compile_controller_routes
from tori_py.logging import current_log_context
from tori_py.starlette import (
    StarletteAdapter,
    StarletteOptions,
    asgi,
    current_request_context,
)
from tori_py.testing import TestingModule


def _asgi(application) -> ASGIApp:
    return application.get_adapter(StarletteAdapter).app


@pytest.mark.asyncio
async def test_no_body_enforces_actual_stream_after_guards_before_dispatch(
    call_http,
    message_body,
) -> None:
    calls: list[str] = []

    class AllowGuard:
        async def can_activate(self, context) -> bool:
            calls.append("guard")
            return True

    class RecordingPipe:
        async def transform(self, value, metadata):
            calls.append("pipe")
            return value

    class RecordingInterceptor:
        async def intercept(self, context, next):
            calls.append("interceptor")
            return await next()

    @controller()
    class Controller:
        @post("/empty")
        @no_body
        @use_guard(AllowGuard())
        @use_pipe(RecordingPipe())
        @use_interceptor(RecordingInterceptor())
        async def empty(
            self,
            value: Annotated[str, Query("value")],
        ) -> HttpResponse:
            calls.append("handler")
            return HttpResponse(b"", status_code=204)

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(
        adapter=StarletteAdapter(StarletteOptions(body_size_limit=4))
    )
    empty = await call_http(
        _asgi(application),
        method="POST",
        path="/empty?value=x",
        headers=[(b"content-length", b"10")],
    )
    assert empty[0]["status"] == 204
    assert message_body(empty[1]) == b""
    assert calls == ["guard", "pipe", "interceptor", "handler"]

    calls.clear()
    supplied = await call_http(
        _asgi(application), method="POST", path="/empty?value=x", body=b"x"
    )
    assert supplied[0]["status"] == 400
    assert b"Request body is not allowed." in message_body(supplied[1])
    assert calls == ["guard"]

    calls.clear()
    oversized = await call_http(
        _asgi(application), method="POST", path="/empty?value=x", body=b"12345"
    )
    assert oversized[0]["status"] == 413
    assert b"Request body exceeds the configured limit." in message_body(oversized[1])
    assert calls == ["guard"]
    await application.close()


@pytest.mark.asyncio
async def test_no_body_does_not_read_stream_before_a_rejecting_guard(
    call_http,
    message_body,
) -> None:
    class DenyGuard:
        async def can_activate(self, context) -> bool:
            return False

    @controller()
    class Controller:
        @post("/empty")
        @no_body
        @use_guard(DenyGuard())
        async def empty(self) -> None:
            raise AssertionError("handler must not run")

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    response = await call_http(
        _asgi(application), method="POST", path="/empty", body=b"unexpected"
    )
    await application.close()

    assert response[0]["status"] == 403
    assert b"Forbidden." in message_body(response[1])


@pytest.mark.asyncio
async def test_no_body_size_classification_is_independent_of_asgi_chunks() -> None:
    calls: list[str] = []

    @controller()
    class Controller:
        @post("/empty")
        @no_body
        async def empty(self) -> None:
            calls.append("handler")

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(
        adapter=StarletteAdapter(StarletteOptions(body_size_limit=4))
    )

    async def request(chunks: list[bytes]) -> tuple[int, int]:
        incoming = [
            {
                "type": "http.request",
                "body": chunk,
                "more_body": index < len(chunks) - 1,
            }
            for index, chunk in enumerate(chunks)
        ]
        receive_count = 0
        sent: list[Message] = []

        async def receive() -> Message:
            nonlocal receive_count
            message = incoming[receive_count]
            receive_count += 1
            return cast(Message, message)

        async def send(message: Message) -> None:
            sent.append(message)

        scope = cast(
            Any,
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/empty",
                "raw_path": b"/empty",
                "query_string": b"",
                "headers": [],
                "client": ("test", 1),
                "server": ("test", 80),
            },
        )
        await _asgi(application)(scope, receive, send)
        start = next(
            message for message in sent if message["type"] == "http.response.start"
        )
        return cast(int, start["status"]), receive_count

    within_limit = await request([b"12", b"34"])
    over_limit = await request([b"12", b"345"])
    await application.close()

    assert within_limit == (400, 2)
    assert over_limit == (413, 2)
    assert calls == []


def test_no_body_route_cannot_also_bind_body() -> None:
    @controller()
    class Controller:
        @post("/invalid")
        @no_body
        async def invalid(self, value: Annotated[object, Body()]) -> None:
            pass

    with pytest.raises(BootstrapError, match="cannot bind a request body") as raised:
        compile_controller_routes(ModuleId(Controller), Controller)

    assert raised.value.diagnostic_code == "route.invalid_binding"


class _RouteReturnModel:
    pass


@pytest.mark.asyncio
async def test_testing_application_serves_raw_bindings_and_context(
    call_http,
    message_body,
    message_headers,
) -> None:
    @controller("/users")
    class UsersController:
        @get("/{user_id}")
        async def read(
            self,
            user_id: Annotated[str, Path("user_id")],
            query: Annotated[str, Query("q")],
            context: Annotated[HttpContext, Context()],
        ) -> dict[str, str]:
            return {
                "user_id": user_id,
                "query": query,
                "request_id": context.request_id or "",
            }

    @module(controllers=[UsersController])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    messages = await call_http(
        _asgi(application),
        path="/users/42?q=raw",
        headers=[(b"x-request-id", b"request-42")],
    )
    assert messages[0]["status"] == 200
    payload = json.loads(message_body(messages[1]))
    assert payload == {"user_id": "42", "query": "raw", "request_id": "request-42"}
    assert (b"x-request-id", b"request-42") in message_headers(messages[0])
    redirect = await call_http(
        _asgi(application),
        path="/users/42/?q=raw",
        headers=[(b"x-request-id", b"redirect-42")],
    )
    assert redirect[0]["status"] == 307
    assert (b"x-request-id", b"redirect-42") in message_headers(redirect[0])
    assert current_request_context() is None
    await application.close()


@pytest.mark.asyncio
async def test_body_binding_repeated_query_and_explicit_response_request_id(
    call_http,
    message_body,
    message_headers,
) -> None:
    @controller()
    class Controller:
        @post("/body")
        @header("Cache-Control", "no-store")
        @header("X-Request-ID", "handler-value")
        async def body(
            self,
            value: Annotated[object, Body()],
        ) -> object:
            return value

        @get("/explicit")
        async def explicit(self) -> Response:
            return Response("ok", headers={"X-Request-ID": "handler-value"})

        @get("/portable")
        @header("X-Decorator", "ignored")
        async def portable(self) -> HttpResponse:
            return HttpResponse(
                b"cached",
                status_code=202,
                headers={
                    "content-type": "text/plain; charset=utf-8",
                    "x-document": "cached",
                    "x-request-id": "handler-value",
                },
            )

        @get("/query")
        async def query(self, values: Annotated[object, Query("value")]) -> object:
            return values

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    body_messages = await call_http(
        _asgi(application),
        method="POST",
        path="/body",
        body=b'{"name":"test"}',
        headers=[
            (b"content-type", b"application/json"),
            (b"x-request-id", b"body-request"),
        ],
    )
    assert json.loads(message_body(body_messages[1])) == {"name": "test"}
    body_headers = message_headers(body_messages[0])
    assert (b"cache-control", b"no-store") in body_headers
    assert (b"x-request-id", b"body-request") in body_headers

    query_messages = await call_http(
        _asgi(application),
        path="/query?value=one&value=two",
    )
    assert json.loads(message_body(query_messages[1])) == ["one", "two"]

    explicit_messages = await call_http(
        _asgi(application),
        path="/explicit",
        headers=[(b"x-request-id", b"framework-value")],
    )
    assert (b"x-request-id", b"framework-value") in message_headers(
        explicit_messages[0]
    )
    portable_messages = await call_http(
        _asgi(application),
        path="/portable",
        headers=[(b"x-request-id", b"portable-request")],
    )
    portable_headers = message_headers(portable_messages[0])
    assert portable_messages[0]["status"] == 202
    assert message_body(portable_messages[1]) == b"cached"
    assert (b"content-type", b"text/plain; charset=utf-8") in portable_headers
    assert (b"x-document", b"cached") in portable_headers
    assert (b"x-decorator", b"ignored") not in portable_headers
    assert portable_headers.count((b"x-request-id", b"portable-request")) == 1
    await application.close()


def test_http_response_validates_and_copies_portable_values() -> None:
    headers = {"content-type": "text/plain"}
    response = HttpResponse(b"body", status_code=201, headers=headers)
    headers["content-type"] = "changed"
    assert response.content == b"body"
    assert response.status_code == 201
    assert response.headers == {"content-type": "text/plain"}
    with pytest.raises(TypeError, match="content must be bytes"):
        HttpResponse(cast(Any, "body"))
    with pytest.raises(ValueError, match="between 200 and 599"):
        HttpResponse(b"", status_code=99)
    with pytest.raises(ValueError, match="between 200 and 599"):
        HttpResponse(b"", status_code=199)
    with pytest.raises(ValueError, match="must not contain content"):
        HttpResponse(b"body", status_code=204)
    with pytest.raises(ValueError, match="HTTP tokens"):
        HttpResponse(b"", headers={"invalid header": "value"})
    with pytest.raises(ValueError, match="CR or LF"):
        HttpResponse(b"", headers={"x-value": "one\r\ntwo"})
    with pytest.raises(ValueError, match="control characters"):
        HttpResponse(b"", headers={"x-value": "one\x00two"})
    with pytest.raises(ValueError, match="control characters"):
        HttpResponse(b"", headers={"x-value": "one\x0btwo"})
    with pytest.raises(ValueError, match="surrounding whitespace"):
        HttpResponse(b"", headers={"x-value": " value"})
    with pytest.raises(ValueError, match="must be unique"):
        HttpResponse(b"", headers={"X-Value": "one", "x-value": "two"})
    with pytest.raises(ValueError, match="transport-owned"):
        HttpResponse(b"", headers={"content-length": "0"})
    with pytest.raises(ValueError, match="valid media type"):
        HttpResponse(b"", headers={"content-type": "text /plain"})
    with pytest.raises(BootstrapError, match="valid media type"):
        header("Content-Type", "text/plain, application/json")
    with pytest.raises(BootstrapError, match="header values must be strings"):
        header("x-value", cast(Any, lambda: "dynamic"))

    with pytest.raises(BootstrapError, match="already declared"):

        @header("X-Value", "outer")
        @header("x-value", "inner")
        def duplicate_headers() -> None:
            pass


@pytest.mark.asyncio
async def test_header_cookie_and_request_provider_bindings_remain_raw(
    call_http,
    message_body,
) -> None:
    @controller()
    class Controller:
        @get("/headers")
        async def headers(
            self,
            header: Annotated[str, Header("X-Value")],
            cookie: Annotated[str, Cookie("session")],
            injected: Annotated[object, Inject("request")],
        ) -> dict[str, object]:
            return {"header": header, "cookie": cookie, "injected": injected}

    @module(
        controllers=[Controller],
        providers=[
            FactoryProvider("request", lambda: "request-value", scope=Scope.REQUEST)
        ],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    messages = await call_http(
        _asgi(application),
        path="/headers",
        headers=[
            (b"x-value", b"raw-header"),
            (b"cookie", b"session=raw-cookie"),
        ],
    )
    assert messages[0]["status"] == 200
    assert json.loads(message_body(messages[1])) == {
        "header": "raw-header",
        "cookie": "raw-cookie",
        "injected": "request-value",
    }
    await application.close()


@pytest.mark.asyncio
async def test_body_media_and_size_errors_are_problem_details(call_http) -> None:
    @controller()
    class Controller:
        @post("/body")
        async def body(self, value: Annotated[object, Body()]) -> object:
            return value

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(
        adapter=StarletteAdapter(StarletteOptions(body_size_limit=1))
    )
    unsupported = await call_http(
        _asgi(application),
        method="POST",
        path="/body",
        body=b"{}",
        headers=[(b"content-type", b"text/plain")],
    )
    assert unsupported[0]["status"] == 415
    oversized = await call_http(
        _asgi(application),
        method="POST",
        path="/body",
        body=b"{}",
        headers=[(b"content-type", b"application/json")],
    )
    assert oversized[0]["status"] == 413
    malformed = await call_http(
        _asgi(application),
        method="POST",
        path="/body",
        body=b"{",
        headers=[(b"content-type", b"application/json")],
    )
    assert malformed[0]["status"] == 400
    await application.close()


@pytest.mark.asyncio
async def test_invalid_request_id_is_replaced_without_echoing_raw_value(
    caplog: pytest.LogCaptureFixture,
    call_http,
    message_headers,
) -> None:
    @controller()
    class Controller:
        @get("/id")
        async def id(self) -> str:
            return "ok"

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    with caplog.at_level("WARNING", logger="tori_py.starlette"):
        messages = await call_http(
            _asgi(application),
            path="/id",
            headers=[(b"x-request-id", b"bad value"), (b"x-request-id", b"second")],
        )
    response_headers = dict(message_headers(messages[0]))
    generated = response_headers[b"x-request-id"].decode()
    assert generated not in {"bad value", "second"}
    assert "bad value" not in caplog.text
    await application.close()


@pytest.mark.asyncio
async def test_http_errors_and_lifespan_wrapper(call_http) -> None:
    @controller()
    class Controller:
        @get("/ok")
        async def ok(self) -> str:
            return "ok"

    @module(controllers=[Controller])
    class Root:
        pass

    async def factory() -> NestApplication:
        return await NestApplication.create(Root, adapter=StarletteAdapter())

    application = asgi(factory)
    messages: list[dict[str, object]] = []
    lifecycle_events = iter(
        cast(
            list[Message],
            [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}],
        )
    )

    async def receive() -> Message:
        return next(lifecycle_events)

    async def send(message: Message) -> None:
        messages.append(dict(message))

    await application(cast(Any, {"type": "lifespan"}), receive, send)
    assert [message["type"] for message in messages] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]

    before_ready = asgi(factory)
    not_ready = await call_http(before_ready, path="/ok")
    assert not_ready[0]["status"] == 503

    started = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    missing = await call_http(_asgi(started), path="/missing")
    wrong_method = await call_http(_asgi(started), method="POST", path="/ok")
    assert missing[0]["status"] == 404
    assert wrong_method[0]["status"] == 405
    await started.close()


@pytest.mark.asyncio
async def test_nest_application_create_is_unstarted_until_lifespan_startup() -> None:
    events: list[str] = []

    @module()
    class Root:
        def __init__(self) -> None:
            events.append("constructed")

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    assert application.state is ApplicationState.COMPILED
    assert events == []
    await application.start()
    assert events == ["constructed"]
    await application.shutdown()


@pytest.mark.asyncio
async def test_asgi_returns_503_after_shutdown_begins(call_http) -> None:
    shutdown_started = asyncio.Event()
    release_shutdown = asyncio.Event()

    @controller()
    class Controller:
        @get("/ok")
        async def ok(self) -> str:
            return "ok"

    @module(controllers=[Controller])
    class Root:
        async def on_application_shutdown(self) -> None:
            shutdown_started.set()
            await release_shutdown.wait()

    async def factory() -> NestApplication:
        return await NestApplication.create(Root, adapter=StarletteAdapter())

    application = asgi(factory)
    events: asyncio.Queue[Message] = asyncio.Queue()
    startup_complete = asyncio.Event()

    async def receive() -> Message:
        return await events.get()

    async def send(message: Message) -> None:
        if message["type"] == "lifespan.startup.complete":
            startup_complete.set()

    lifespan = asyncio.create_task(
        application(cast(Any, {"type": "lifespan"}), receive, send)
    )
    await events.put({"type": "lifespan.startup"})
    await startup_complete.wait()
    await events.put({"type": "lifespan.shutdown"})
    await shutdown_started.wait()
    response = await call_http(application, path="/ok")
    assert response[0]["status"] == 503
    release_shutdown.set()
    await lifespan


@pytest.mark.asyncio
async def test_asgi_rejects_non_awaitable_factory_result() -> None:
    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    messages: list[dict[str, object]] = []

    async def send(message: Message) -> None:
        messages.append(dict(message))

    invalid = asgi(cast(Any, lambda: object()))
    await invalid(cast(Any, {"type": "lifespan"}), receive, send)
    assert messages[0]["type"] == "lifespan.startup.failed"


@pytest.mark.asyncio
async def test_route_binding_validation_happens_at_compile() -> None:
    @controller()
    class Invalid:
        @get("/invalid")
        async def invalid(self, value: str) -> str:
            return value

    @module(controllers=[Invalid])
    class InvalidRoot:
        pass

    with pytest.raises(BootstrapError, match="exactly one binding marker"):
        await TestingModule.create(InvalidRoot).compile(adapter=StarletteAdapter())


@pytest.mark.asyncio
async def test_controller_route_compiler_retains_return_annotations_and_is_canonical(
    monkeypatch: pytest.MonkeyPatch,
    call_http,
) -> None:
    @controller()
    class Controller:
        @get("/sync")
        def sync(self) -> "_RouteReturnModel":  # noqa: UP037 - exercise resolution
            return _RouteReturnModel()

        @get("/async")
        async def async_result(self) -> list[str]:
            return []

        @get("/none")
        async def explicit_none(self) -> None:
            return None

        @get("/absent")
        async def absent(self):
            return None

    @module(controllers=[Controller])
    class Root:
        pass

    hint_calls = 0
    signature_calls = 0
    original_hints = routes_module.get_type_hints
    original_signature = routes_module.inspect.signature
    handlers = {
        Controller.sync,
        Controller.async_result,
        Controller.explicit_none,
        Controller.absent,
    }

    def counting_get_type_hints(*args: Any, **kwargs: Any) -> dict[str, object]:
        nonlocal hint_calls
        if args and args[0] in handlers:
            hint_calls += 1
        return cast(dict[str, object], original_hints(*args, **kwargs))

    def counting_signature(*args: Any, **kwargs: Any) -> inspect.Signature:
        nonlocal signature_calls
        if args and args[0] in handlers:
            signature_calls += 1
        return original_signature(*args, **kwargs)

    monkeypatch.setattr(routes_module, "get_type_hints", counting_get_type_hints)
    monkeypatch.setattr(routes_module.inspect, "signature", counting_signature)
    plans = compile_controller_routes(ModuleId(Root), Controller)
    by_path = {plan.path: plan for plan in plans}

    assert hint_calls == signature_calls == 4
    assert by_path["/sync"].return_annotation is _RouteReturnModel
    assert by_path["/async"].return_annotation == list[str]
    assert by_path["/none"].return_annotation is type(None)
    assert by_path["/absent"].return_annotation is inspect.Signature.empty
    assert by_path["/sync"].handler is Controller.sync
    with pytest.raises(AttributeError):
        cast(Any, plans).append(by_path["/sync"])

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    assert hint_calls == signature_calls == 8
    await application.start()
    response = await call_http(_asgi(application), path="/async")
    assert response[0]["status"] == 200
    assert hint_calls == signature_calls == 8
    await application.shutdown()


@pytest.mark.asyncio
async def test_duplicate_routes_and_invalid_context_are_compile_errors() -> None:
    @controller()
    class Duplicate:
        @get("/same")
        async def first(self) -> str:
            return "first"

        @get("/same")
        async def second(self) -> str:
            return "second"

    @module(controllers=[Duplicate])
    class DuplicateRoot:
        pass

    with pytest.raises(BootstrapError, match="duplicate"):
        await TestingModule.create(DuplicateRoot).compile(adapter=StarletteAdapter())

    @controller()
    class InvalidContext:
        @get("/context")
        async def context(self, value: Annotated[str, Context()]) -> str:
            return value

    @module(controllers=[InvalidContext])
    class InvalidContextRoot:
        pass

    with pytest.raises(BootstrapError, match="HttpContext"):
        await TestingModule.create(InvalidContextRoot).compile(
            adapter=StarletteAdapter()
        )

    class UnsupportedContext(HttpContext):
        pass

    @controller()
    class Unsupported:
        @get("/unsupported")
        async def context(
            self,
            value: Annotated[UnsupportedContext, Context()],
        ) -> str:
            return value.route_id or ""

    @module(controllers=[Unsupported])
    class UnsupportedRoot:
        pass

    with pytest.raises(BootstrapError, match="not compatible"):
        await TestingModule.create(UnsupportedRoot).compile(adapter=StarletteAdapter())


@pytest.mark.asyncio
async def test_response_and_request_cleanup_keep_matched_context(call_http) -> None:
    events: list[tuple[str | None, object]] = []

    @asynccontextmanager
    async def resource() -> AsyncIterator[str]:
        yield "resource"
        context = current_request_context()
        events.append(
            (
                None if context is None else context.route_id,
                current_log_context().fields.get("request_id"),
            )
        )

    async def background() -> None:
        context = current_request_context()
        events.append(
            (
                None if context is None else context.route_id,
                current_log_context().fields.get("request_id"),
            )
        )

    @controller()
    class Controller:
        @get("/context-lifetime")
        async def context_lifetime(
            self,
            value: Annotated[str, Inject("resource")],
        ) -> Response:
            return Response(value, background=BackgroundTask(background))

    @module(
        controllers=[Controller],
        providers=[FactoryProvider("resource", resource, scope=Scope.REQUEST)],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    messages = await call_http(
        _asgi(application),
        path="/context-lifetime",
        headers=[(b"x-request-id", b"context-lifetime")],
    )
    assert messages[0]["status"] == 200
    assert events == [
        ("GET /context-lifetime", "context-lifetime"),
        ("GET /context-lifetime", "context-lifetime"),
    ]
    assert current_request_context() is None
    await application.close()


@pytest.mark.asyncio
async def test_controller_is_bound_at_startup_not_resolved_per_request(
    call_http,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = 0

    @controller()
    class Controller:
        def __init__(self) -> None:
            nonlocal constructed
            constructed += 1

        @get("/bound")
        async def bound(self) -> str:
            return "bound"

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    assert constructed == 1

    def fail_request_resolution(self, module_id):
        del self, module_id
        raise AssertionError("controller was resolved during request execution")

    monkeypatch.setattr(RequestScope, "resolver_for", fail_request_resolution)
    first = await call_http(_asgi(application), path="/bound")
    second = await call_http(_asgi(application), path="/bound")
    assert first[0]["status"] == second[0]["status"] == 200
    assert constructed == 1
    await application.close()


@pytest.mark.asyncio
async def test_disconnect_after_final_body_does_not_cancel_background_work() -> None:
    background_started = asyncio.Event()
    release_background = asyncio.Event()
    background_completed = asyncio.Event()

    async def background() -> None:
        background_started.set()
        await release_background.wait()
        background_completed.set()

    @controller()
    class Controller:
        @get("/background")
        async def response(self) -> Response:
            return Response("ok", background=BackgroundTask(background))

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    incoming: asyncio.Queue[Message] = asyncio.Queue()
    sent: list[Message] = []

    async def receive() -> Message:
        return await incoming.get()

    async def send(message: Message) -> None:
        sent.append(message)

    scope = cast(
        Any,
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/background",
            "raw_path": b"/background",
            "query_string": b"",
            "headers": [],
            "client": ("test", 1),
            "server": ("test", 80),
        },
    )
    await incoming.put({"type": "http.request", "body": b"", "more_body": False})
    request = asyncio.ensure_future(_asgi(application)(scope, receive, send))
    await asyncio.wait_for(background_started.wait(), timeout=1)
    await incoming.put({"type": "http.disconnect"})
    await asyncio.sleep(0)
    assert not request.done()

    release_background.set()
    await asyncio.wait_for(request, timeout=1)
    assert sent[-1]["type"] == "http.response.body"
    assert background_completed.is_set()
    await application.close()


@pytest.mark.asyncio
async def test_client_disconnect_cancels_handler_and_cleans_request_scope() -> None:
    handler_started = asyncio.Event()
    events: list[str | None] = []

    @asynccontextmanager
    async def resource() -> AsyncIterator[str]:
        yield "resource"
        context = current_request_context()
        events.append(None if context is None else context.route_id)

    @controller()
    class Controller:
        @get("/wait")
        async def wait(
            self,
            value: Annotated[str, Inject("resource")],
        ) -> None:
            del value
            handler_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                events.append("cancelled")

    @module(
        controllers=[Controller],
        providers=[FactoryProvider("resource", resource, scope=Scope.REQUEST)],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    incoming: asyncio.Queue[Message] = asyncio.Queue()
    sent: list[Message] = []

    async def receive() -> Message:
        return await incoming.get()

    async def send(message: Message) -> None:
        sent.append(message)

    scope = cast(
        Any,
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/wait",
            "raw_path": b"/wait",
            "query_string": b"",
            "headers": [],
            "client": ("test", 1),
            "server": ("test", 80),
        },
    )
    await incoming.put({"type": "http.request", "body": b"", "more_body": False})
    request = asyncio.ensure_future(_asgi(application)(scope, receive, send))
    await asyncio.wait_for(handler_started.wait(), timeout=1)
    await incoming.put({"type": "http.disconnect"})
    await asyncio.wait_for(request, timeout=1)

    assert sent == []
    assert events == ["cancelled", "GET /wait"]
    assert current_request_context() is None
    await application.close()
