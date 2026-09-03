from __future__ import annotations

import asyncio
import json
from collections.abc import MutableMapping
from typing import Annotated, Any, cast
from uuid import UUID

import pytest
import tori_py.asgi.application as asgi_application
import tori_py.core.runtime as runtime_module
from tori_py import (
    Body,
    BodyStream,
    BootstrapError,
    Context,
    Cookie,
    Header,
    HttpResponse,
    Inject,
    NestApplication,
    Path,
    Query,
    ValueProvider,
    controller,
    delete,
    get,
    module,
    no_body,
    options,
    patch,
    post,
    put,
)
from tori_py.asgi import (
    AsgiAdapter,
    AsgiOptions,
    RequestContext,
    asgi,
    current_request_context,
)
from tori_py.http import HttpBodyStream
from tori_py.testing import TestingModule

type Message = MutableMapping[str, Any]


def _asgi(application):
    return application.get_adapter(AsgiAdapter).app


@pytest.mark.asyncio
async def test_asgi_adapter_binds_native_request_values(
    call_http, message_body
) -> None:
    service = object()

    @controller()
    class Controller:
        @get("/items/{item_id:int}")
        async def item(
            self,
            item_id: Annotated[int, Path("item_id")],
            tags: Annotated[object, Query("tag")],
            agent: Annotated[str, Header("x-agent")],
            session: Annotated[str, Cookie("session")],
            context: Annotated[RequestContext, Context()],
            dependency: Annotated[object, Inject("service")],
        ) -> dict[str, object]:
            return {
                "item_id": item_id,
                "tags": tags,
                "agent": agent,
                "session": session,
                "method": context.method,
                "path": context.path,
                "dependency": dependency is service,
            }

    @module(
        controllers=[Controller],
        providers=[ValueProvider("service", service)],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=AsgiAdapter())
    response = await call_http(
        _asgi(application),
        path="/items/42?tag=one&tag=two",
        headers=[
            (b"x-agent", b"test"),
            (b"cookie", b"session=abc"),
        ],
    )

    assert response[0]["status"] == 200
    assert json.loads(message_body(response[1])) == {
        "item_id": 42,
        "tags": ["one", "two"],
        "agent": "test",
        "session": "abc",
        "method": "GET",
        "path": "/items/42",
        "dependency": True,
    }
    await application.close()


@pytest.mark.asyncio
async def test_asgi_endpoint_execution_is_compiled_during_binding_not_per_request(
    monkeypatch, call_http
) -> None:
    @controller()
    class Controller:
        @get("/compiled")
        async def compiled(self) -> str:
            return "ok"

    @module(controllers=[Controller])
    class Root:
        pass

    compiled = 0
    compile_endpoint = asgi_application.compile_endpoint

    def count_compilations(*args, **kwargs):
        nonlocal compiled
        compiled += 1
        return compile_endpoint(*args, **kwargs)

    monkeypatch.setattr(asgi_application, "compile_endpoint", count_compilations)
    application = await TestingModule.create(Root).compile(adapter=AsgiAdapter())

    assert compiled == 1
    await call_http(_asgi(application), path="/compiled")
    await call_http(_asgi(application), path="/compiled")
    assert compiled == 1
    await application.close()


@pytest.mark.asyncio
async def test_asgi_injection_uses_the_provider_reference_compiled_for_the_route(
    monkeypatch: pytest.MonkeyPatch,
    call_http,
    message_body,
) -> None:
    @controller()
    class Controller:
        @get("/compiled-injection")
        async def compiled_injection(
            self,
            value: Annotated[str, Inject("value")],
        ) -> str:
            return value

    @module(
        controllers=[Controller],
        providers=[ValueProvider("value", "compiled")],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=AsgiAdapter())

    async def fail_token_resolution(*args, **kwargs):
        del args, kwargs
        raise AssertionError("route injection must use its compiled provider ref")

    monkeypatch.setattr(runtime_module._Resolver, "resolve", fail_token_resolution)
    response = await call_http(_asgi(application), path="/compiled-injection")

    assert json.loads(message_body(response[1])) == "compiled"
    await application.close()


@pytest.mark.asyncio
async def test_asgi_rejects_an_unresolved_route_injection_during_compilation() -> None:
    @controller()
    class Controller:
        @get("/missing")
        async def missing(
            self,
            value: Annotated[object, Inject("missing")],
        ) -> object:
            return value

    @module(controllers=[Controller])
    class Root:
        pass

    with pytest.raises(BootstrapError) as captured:
        await TestingModule.create(Root).compile(adapter=AsgiAdapter())

    assert captured.value.diagnostic_code == "provider.unresolved"


@pytest.mark.asyncio
async def test_asgi_router_preserves_order_head_405_and_slash_redirect(
    call_http, message_body, message_headers
) -> None:
    @controller()
    class Controller:
        @get("/files/{value}")
        async def dynamic(self, value: Annotated[str, Path("value")]) -> str:
            return f"dynamic:{value}"

        @get("/files/static")
        async def static(self) -> str:
            return "static"

        @get("/slash/")
        async def slash(self) -> str:
            return "slash"

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=AsgiAdapter())
    ordered = await call_http(_asgi(application), path="/files/static")
    head = await call_http(_asgi(application), method="HEAD", path="/files/value")
    wrong_method = await call_http(
        _asgi(application), method="POST", path="/files/value"
    )
    redirect = await call_http(_asgi(application), path="/slash")

    assert json.loads(message_body(ordered[1])) == "dynamic:static"
    assert head[0]["status"] == 200
    assert message_body(head[1]) == b""
    assert wrong_method[0]["status"] == 405
    assert set(dict(message_headers(wrong_method[0]))[b"allow"].split(b", ")) == {
        b"GET",
        b"HEAD",
    }
    assert redirect[0]["status"] == 307
    await application.close()


@pytest.mark.asyncio
async def test_asgi_adapter_reads_json_and_writes_portable_responses(
    call_http, message_body, message_headers
) -> None:
    @controller()
    class Controller:
        @post("/echo")
        async def echo(self, body: Annotated[object, Body()]) -> object:
            return body

        @get("/raw")
        async def raw(self) -> HttpResponse:
            return HttpResponse(
                b"raw",
                status_code=202,
                headers={"content-type": "text/plain", "x-value": "one"},
            )

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=AsgiAdapter())
    echoed = await call_http(
        _asgi(application),
        method="POST",
        path="/echo",
        body=b'{"value":1}',
        headers=[(b"content-type", b"application/json")],
    )
    raw = await call_http(_asgi(application), path="/raw")

    assert json.loads(message_body(echoed[1])) == {"value": 1}
    assert raw[0]["status"] == 202
    assert message_body(raw[1]) == b"raw"
    assert dict(message_headers(raw[0]))[b"x-value"] == b"one"
    await application.close()


@pytest.mark.asyncio
async def test_asgi_adapter_renders_routing_errors_and_request_ids(
    call_http, message_body, message_headers
) -> None:
    @controller()
    class Controller:
        @get("/failure")
        async def failure(self) -> None:
            raise RuntimeError("secret")

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=AsgiAdapter())
    missing = await call_http(
        _asgi(application),
        path="/missing",
        headers=[(b"x-request-id", b"request-1")],
    )
    failed = await call_http(_asgi(application), path="/failure")

    assert missing[0]["status"] == 404
    assert json.loads(message_body(missing[1]))["instance"] == "/missing"
    assert dict(message_headers(missing[0]))[b"x-request-id"] == b"request-1"
    assert failed[0]["status"] == 500
    assert b"secret" not in message_body(failed[1])
    await application.close()


@pytest.mark.asyncio
async def test_native_asgi_wrapper_owns_lifespan_and_readiness(call_http) -> None:
    @controller()
    class Controller:
        @get("/ok")
        async def ok(self) -> str:
            return "ok"

    @module(controllers=[Controller])
    class Root:
        pass

    async def factory() -> NestApplication:
        return await NestApplication.create(Root, adapter=AsgiAdapter())

    wrapper = asgi(factory)
    not_ready = await call_http(wrapper, path="/ok")
    assert not_ready[0]["status"] == 503

    events = iter(
        cast(
            list[Message],
            [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}],
        )
    )
    sent: list[Message] = []

    async def receive() -> Message:
        return next(events)

    async def send(message: Message) -> None:
        sent.append(message)

    await wrapper(cast(Any, {"type": "lifespan"}), receive, send)
    assert [message["type"] for message in sent] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]


@pytest.mark.asyncio
async def test_testing_http_client_supports_asgi_adapter() -> None:
    @controller()
    class Controller:
        @get("/ok")
        async def ok(self) -> str:
            return "ok"

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=AsgiAdapter())
    async with application.http_client() as client:
        response = await client.get("/ok")

    assert response.status_code == 200
    assert response.json() == "ok"
    await application.close()


@pytest.mark.asyncio
async def test_bodyless_client_disconnect_cancels_the_handler() -> None:
    handler_started = asyncio.Event()
    handler_cancelled = asyncio.Event()

    @controller()
    class Controller:
        @get("/wait")
        async def wait(
            self,
            _handler: Annotated[str, Query("_handler")],
        ) -> None:
            assert _handler == "value"
            handler_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                handler_cancelled.set()

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=AsgiAdapter())
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
            "query_string": b"_handler=value",
            "headers": [],
            "client": ("test", 1),
            "server": ("test", 80),
        },
    )
    await incoming.put({"type": "http.request", "body": b"", "more_body": False})
    request = asyncio.create_task(_asgi(application)(scope, receive, send))
    await asyncio.wait_for(handler_started.wait(), timeout=1)
    await incoming.put({"type": "http.disconnect"})
    await asyncio.wait_for(request, timeout=1)

    assert sent == []
    assert handler_cancelled.is_set()
    assert current_request_context() is None
    await application.close()


@pytest.mark.asyncio
async def test_asgi_router_supports_methods_and_path_converters(
    call_http, message_body
) -> None:
    identifier = UUID("12345678-1234-5678-1234-567812345678")

    @controller()
    class Controller:
        @put("/convert/{ratio:float}/{identifier:uuid}/{rest:path}")
        async def convert(
            self,
            ratio: Annotated[float, Path("ratio")],
            identifier: Annotated[UUID, Path("identifier")],
            rest: Annotated[str, Path("rest")],
        ) -> dict[str, object]:
            return {
                "ratio": ratio,
                "identifier": str(identifier),
                "rest": rest,
            }

        @patch("/patch")
        async def patch_value(self) -> str:
            return "patch"

        @delete("/delete")
        async def delete_value(self) -> str:
            return "delete"

        @options("/options")
        async def options_value(self) -> str:
            return "options"

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=AsgiAdapter())
    converted = await call_http(
        _asgi(application),
        method="PUT",
        path=f"/convert/1.5/{identifier}/nested/path",
    )
    patched = await call_http(_asgi(application), method="PATCH", path="/patch")
    deleted = await call_http(_asgi(application), method="DELETE", path="/delete")
    optioned = await call_http(_asgi(application), method="OPTIONS", path="/options")

    assert json.loads(message_body(converted[1])) == {
        "ratio": 1.5,
        "identifier": str(identifier),
        "rest": "nested/path",
    }
    assert json.loads(message_body(patched[1])) == "patch"
    assert json.loads(message_body(deleted[1])) == "delete"
    assert json.loads(message_body(optioned[1])) == "options"
    await application.close()


@pytest.mark.asyncio
async def test_asgi_adapter_enforces_body_contracts(call_http, message_body) -> None:
    @controller()
    class Controller:
        @post("/json")
        async def json_body(self, body: Annotated[object, Body()]) -> object:
            return body

        @post("/empty")
        @no_body
        async def empty(self) -> HttpResponse:
            return HttpResponse(b"", status_code=204)

        @post("/stream")
        async def stream(
            self,
            body: Annotated[HttpBodyStream, BodyStream(max_bytes=4)],
        ) -> str:
            return b"".join([chunk async for chunk in body]).decode()

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(
        adapter=AsgiAdapter(AsgiOptions(body_size_limit=4))
    )
    too_large = await call_http(
        _asgi(application),
        method="POST",
        path="/json",
        body=b'{"x":1}',
        headers=[(b"content-type", b"application/json")],
    )
    malformed = await call_http(
        _asgi(application),
        method="POST",
        path="/json",
        body=b"bad",
        headers=[(b"content-type", b"application/json")],
    )
    forbidden = await call_http(
        _asgi(application), method="POST", path="/empty", body=b"x"
    )
    streamed = await call_http(
        _asgi(application), method="POST", path="/stream", body=b"abcd"
    )
    stream_too_large = await call_http(
        _asgi(application), method="POST", path="/stream", body=b"abcde"
    )

    assert too_large[0]["status"] == 413
    assert malformed[0]["status"] == 400
    assert forbidden[0]["status"] == 400
    assert json.loads(message_body(streamed[1])) == "abcd"
    assert stream_too_large[0]["status"] == 413
    await application.close()
