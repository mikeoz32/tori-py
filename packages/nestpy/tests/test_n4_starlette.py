import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, cast

import pytest
from nestpy import (
    Body,
    BootstrapError,
    Context,
    Cookie,
    FactoryProvider,
    Header,
    Inject,
    Path,
    Query,
    Scope,
    StarletteOptions,
    controller,
    get,
    module,
    post,
)
from nestpy.core.runtime import ApplicationState
from nestpy.starlette import (
    NestApplication,
    RequestContext,
    asgi,
    current_request_context,
)
from nestpy.testing import TestingModule
from starlette.responses import Response
from starlette.types import ASGIApp, Message


async def call_http(
    app: Callable[..., Awaitable[None]],
    *,
    method: str = "GET",
    path: str = "/",
    body: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }

    async def send(message: Message) -> None:
        messages.append(dict(message))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path.split("?", 1)[0],
        "raw_path": path.encode(),
        "query_string": (path.split("?", 1)[1].encode() if "?" in path else b""),
        "headers": headers or [],
        "client": ("test", 1),
        "server": ("test", 80),
    }
    await cast(ASGIApp, app)(scope, receive, send)
    return messages


def message_body(message: dict[str, object]) -> bytes:
    return cast(bytes, message["body"])


def message_headers(message: dict[str, object]) -> list[tuple[bytes, bytes]]:
    return cast(list[tuple[bytes, bytes]], message["headers"])


@pytest.mark.asyncio
async def test_testing_application_serves_raw_bindings_and_context() -> None:
    @controller("/users")
    class UsersController:
        @get("/{user_id}")
        async def read(
            self,
            user_id: Annotated[str, Path("user_id")],
            query: Annotated[str, Query("q")],
            context: Annotated[RequestContext, Context()],
        ) -> dict[str, str]:
            return {
                "user_id": user_id,
                "query": query,
                "request_id": context.request_id or "",
            }

    @module(controllers=[UsersController])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    messages = await call_http(
        application.asgi,
        path="/users/42?q=raw",
        headers=[(b"x-request-id", b"request-42")],
    )
    assert messages[0]["status"] == 200
    payload = json.loads(message_body(messages[1]))
    assert payload == {"user_id": "42", "query": "raw", "request_id": "request-42"}
    assert (b"x-request-id", b"request-42") in message_headers(messages[0])
    assert current_request_context() is None
    await application.close()


@pytest.mark.asyncio
async def test_body_binding_repeated_query_and_explicit_response_request_id() -> None:
    @controller()
    class Controller:
        @post("/body")
        async def body(
            self,
            value: Annotated[object, Body()],
        ) -> object:
            return value

        @get("/explicit")
        async def explicit(self) -> Response:
            return Response("ok", headers={"X-Request-ID": "handler-value"})

        @get("/query")
        async def query(self, values: Annotated[object, Query("value")]) -> object:
            return values

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    body_messages = await call_http(
        application.asgi,
        method="POST",
        path="/body",
        body=b'{"name":"test"}',
        headers=[(b"content-type", b"application/json")],
    )
    assert json.loads(message_body(body_messages[1])) == {"name": "test"}

    query_messages = await call_http(
        application.asgi,
        path="/query?value=one&value=two",
    )
    assert json.loads(message_body(query_messages[1])) == ["one", "two"]

    explicit_messages = await call_http(
        application.asgi,
        path="/explicit",
        headers=[(b"x-request-id", b"framework-value")],
    )
    assert (b"x-request-id", b"framework-value") in message_headers(
        explicit_messages[0]
    )
    await application.close()


@pytest.mark.asyncio
async def test_header_cookie_and_request_provider_bindings_remain_raw() -> None:
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

    application = await TestingModule.create(Root).compile()
    messages = await call_http(
        application.asgi,
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
async def test_body_media_and_size_errors_are_problem_details() -> None:
    @controller()
    class Controller:
        @post("/body")
        async def body(self, value: Annotated[object, Body()]) -> object:
            return value

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(
        http=StarletteOptions(body_size_limit=1)
    )
    unsupported = await call_http(
        application.asgi,
        method="POST",
        path="/body",
        body=b"{}",
        headers=[(b"content-type", b"text/plain")],
    )
    assert unsupported[0]["status"] == 415
    oversized = await call_http(
        application.asgi,
        method="POST",
        path="/body",
        body=b"{}",
        headers=[(b"content-type", b"application/json")],
    )
    assert oversized[0]["status"] == 413
    malformed = await call_http(
        application.asgi,
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
) -> None:
    @controller()
    class Controller:
        @get("/id")
        async def id(self) -> str:
            return "ok"

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    with caplog.at_level("WARNING", logger="nestpy.starlette"):
        messages = await call_http(
            application.asgi,
            path="/id",
            headers=[(b"x-request-id", b"bad value"), (b"x-request-id", b"second")],
        )
    response_headers = dict(message_headers(messages[0]))
    generated = response_headers[b"x-request-id"].decode()
    assert generated not in {"bad value", "second"}
    assert "bad value" not in caplog.text
    await application.close()


@pytest.mark.asyncio
async def test_http_errors_and_lifespan_wrapper() -> None:
    @controller()
    class Controller:
        @get("/ok")
        async def ok(self) -> str:
            return "ok"

    @module(controllers=[Controller])
    class Root:
        pass

    async def factory() -> NestApplication:
        return await NestApplication.create(Root)

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

    started = await TestingModule.create(Root).compile()
    missing = await call_http(started.asgi, path="/missing")
    wrong_method = await call_http(started.asgi, method="POST", path="/ok")
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

    application = await NestApplication.create(Root)
    assert application.state is ApplicationState.COMPILED
    assert events == []
    await application.start()
    assert events == ["constructed"]
    await application.shutdown()


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
        await TestingModule.create(InvalidRoot).compile()


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
        await TestingModule.create(DuplicateRoot).compile()

    @controller()
    class InvalidContext:
        @get("/context")
        async def context(self, value: Annotated[str, Context()]) -> str:
            return value

    @module(controllers=[InvalidContext])
    class InvalidContextRoot:
        pass

    with pytest.raises(BootstrapError, match="RequestContext"):
        await TestingModule.create(InvalidContextRoot).compile()
