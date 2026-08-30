import asyncio
import json
import logging
import uuid
from typing import Annotated, Any, cast

import msgspec
import pytest
import tori_py.starlette.routes as routes_module
from starlette.requests import ClientDisconnect
from starlette.responses import Response
from starlette.types import ASGIApp, Message
from tori_py import (
    Body,
    BootstrapError,
    ClassProvider,
    Context,
    DeferredModule,
    FactoryProvider,
    Inject,
    ModuleSpec,
    NestApplication,
    Path,
    PipelineOptions,
    PipelineResult,
    Query,
    Scope,
    ValueProvider,
    controller,
    get,
    module,
    post,
    use_filter,
    use_filters,
    use_guard,
    use_guards,
    use_interceptor,
    use_interceptors,
    use_middleware,
    use_pipe,
    use_pipes,
)
from tori_py.http import HttpResponse
from tori_py.logging import use_log_context
from tori_py.starlette import (
    RequestContext,
    StarletteAdapter,
)
from tori_py.testing import TestingModule

_SENSITIVE_HTTP_VALUES = (
    "caller-request-id-sentinel",
    "sentinel-handle",
    "workflow-ref-RP7-secret",
    "cursor-secret-42",
    "duplicate key value violates unique constraint users_handle_key",
    "https://internal.example/private?token=secret",
)
_SENSITIVE_EXCEPTION_TEXT = " | ".join(_SENSITIVE_HTTP_VALUES[2:])


def _asgi(application) -> ASGIApp:
    return application.get_adapter(StarletteAdapter).app


def _assert_sanitized_http_records(
    records: list[logging.LogRecord],
    expected_codes: list[str],
) -> None:
    assert [record.getMessage() for record in records] == expected_codes
    standard_fields = logging.makeLogRecord({}).__dict__.keys() | {
        "asctime",
        "message",
    }
    formatter = logging.Formatter("%(message)s|%(event_id)s")
    event_ids: set[str] = set()
    for record in records:
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in standard_fields
        }
        assert set(extra) == {"event_id"}
        event_id = cast(str, extra["event_id"])
        assert str(uuid.UUID(event_id)) == event_id
        assert event_id not in event_ids
        event_ids.add(event_id)
        assert record.args == ()
        assert record.exc_info is None
        assert record.exc_text is None
        rendered = formatter.format(record)
        inspected = " ".join(
            (
                record.getMessage(),
                repr(record.args),
                repr(extra),
                repr(record.exc_info),
                repr(record.exc_text),
                rendered,
            )
        )
        for value in _SENSITIVE_HTTP_VALUES:
            assert value not in inspected


class Payload(msgspec.Struct):
    value: int


@pytest.mark.asyncio
async def test_pipeline_order_and_argument_metadata(call_http, message_body) -> None:
    events: list[str] = []
    pipe_names: list[str] = []

    class RecordingMiddleware:
        def __init__(self, name: str) -> None:
            self.name = name

        async def handle(self, context, next):
            events.append(f"{self.name}-in")
            result = await next()
            events.append(f"{self.name}-out")
            return result

    class RecordingGuard:
        def __init__(self, name: str) -> None:
            self.name = name

        async def can_activate(self, context) -> bool:
            events.append(self.name)
            return True

    class RecordingPipe:
        def __init__(self, name: str) -> None:
            self.name = name

        async def transform(self, value, metadata):
            pipe_names.append(f"{self.name}:{metadata.parameter_name}")
            return f"{value}-{self.name}"

    class RecordingInterceptor:
        def __init__(self, name: str) -> None:
            self.name = name

        async def intercept(self, context, next):
            events.append(f"{self.name}-in")
            result = await next()
            events.append(f"{self.name}-out")
            return result

    class RootMiddleware(RecordingMiddleware):
        def __init__(self) -> None:
            super().__init__("global-middleware")

    class ControllerMiddleware(RecordingMiddleware):
        def __init__(self) -> None:
            super().__init__("controller-middleware")

    class RouteMiddleware(RecordingMiddleware):
        def __init__(self) -> None:
            super().__init__("route-middleware")

    class RootGuard(RecordingGuard):
        def __init__(self) -> None:
            super().__init__("global-guard")

    class ControllerGuard(RecordingGuard):
        def __init__(self) -> None:
            super().__init__("controller-guard")

    class RouteGuard(RecordingGuard):
        def __init__(self) -> None:
            super().__init__("route-guard")

    class RootPipe(RecordingPipe):
        def __init__(self) -> None:
            super().__init__("global-pipe")

    class ControllerPipe(RecordingPipe):
        def __init__(self) -> None:
            super().__init__("controller-pipe")

    class RoutePipe(RecordingPipe):
        def __init__(self) -> None:
            super().__init__("route-pipe")

    class RootInterceptor(RecordingInterceptor):
        def __init__(self) -> None:
            super().__init__("global-interceptor")

    class ControllerInterceptor(RecordingInterceptor):
        def __init__(self) -> None:
            super().__init__("controller-interceptor")

    class RouteInterceptor(RecordingInterceptor):
        def __init__(self) -> None:
            super().__init__("route-interceptor")

    @controller()
    @use_middleware("controller-middleware")
    @use_guards("controller-guard")
    @use_pipes("controller-pipe")
    @use_interceptors("controller-interceptor")
    class Controller:
        @get("/pipeline")
        @use_middleware("route-middleware")
        @use_guards("route-guard")
        @use_pipes("route-pipe")
        @use_interceptors("route-interceptor")
        async def pipeline(
            self,
            value: Annotated[str, Query("value")],
            context: Annotated[RequestContext, Context()],
            injected: Annotated[object, Inject("injected")],
        ) -> str:
            del context, injected
            events.append("handler")
            return value

    @module(
        controllers=[Controller],
        providers=[
            ClassProvider("global-middleware", RootMiddleware),
            ClassProvider("controller-middleware", ControllerMiddleware),
            ClassProvider("route-middleware", RouteMiddleware),
            ClassProvider("global-guard", RootGuard),
            ClassProvider("controller-guard", ControllerGuard),
            ClassProvider("route-guard", RouteGuard),
            ClassProvider("global-pipe", RootPipe),
            ClassProvider("controller-pipe", ControllerPipe),
            ClassProvider("route-pipe", RoutePipe),
            ClassProvider("global-interceptor", RootInterceptor),
            ClassProvider("controller-interceptor", ControllerInterceptor),
            ClassProvider("route-interceptor", RouteInterceptor),
            ValueProvider("injected", "value"),
        ],
    )
    class Root:
        pass

    options = PipelineOptions(
        middleware=("global-middleware",),
        guards=("global-guard",),
        pipes=("global-pipe",),
        interceptors=("global-interceptor",),
    )
    application = await TestingModule.create(Root).compile(
        pipeline=options,
        adapter=StarletteAdapter(),
    )
    messages = await call_http(_asgi(application), path="/pipeline?value=raw")
    assert (
        json.loads(message_body(messages[1]))
        == "raw-global-pipe-controller-pipe-route-pipe"
    )
    assert pipe_names == [
        "global-pipe:value",
        "controller-pipe:value",
        "route-pipe:value",
    ]
    assert events == [
        "global-middleware-in",
        "controller-middleware-in",
        "route-middleware-in",
        "global-guard",
        "controller-guard",
        "route-guard",
        "global-interceptor-in",
        "controller-interceptor-in",
        "route-interceptor-in",
        "handler",
        "route-interceptor-out",
        "controller-interceptor-out",
        "global-interceptor-out",
        "route-middleware-out",
        "controller-middleware-out",
        "global-middleware-out",
    ]
    await application.close()


@pytest.mark.asyncio
async def test_validation_pipe_is_opt_in_and_context_inject_are_excluded(
    call_http,
    message_body,
) -> None:
    @controller()
    class Controller:
        @get("/number")
        async def number(self, value: Annotated[int, Query("value")]) -> int:
            return value

        @post("/payload")
        async def payload(
            self,
            value: Annotated[Payload, Body()],
            context: Annotated[RequestContext, Context()],
            injected: Annotated[object, Inject("injected")],
        ) -> dict[str, object]:
            return {
                "value": value.value,
                "context": context is not None,
                "injected": injected,
            }

    class ValidationPipe:
        async def transform(self, value, metadata):
            from tori_py.http import MsgspecValidationPipe

            return await MsgspecValidationPipe().transform(value, metadata)

    @module(
        controllers=[Controller],
        providers=[
            ValueProvider("validation", ValidationPipe()),
            ValueProvider("injected", "injected-value"),
        ],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile(
        pipeline=PipelineOptions(pipes=("validation",)),
        adapter=StarletteAdapter(),
    )
    messages = await call_http(
        _asgi(application),
        method="POST",
        path="/payload",
        body=b'{"value": 7}',
        headers=[(b"content-type", b"application/json")],
    )
    assert json.loads(message_body(messages[1])) == {
        "value": 7,
        "context": True,
        "injected": "injected-value",
    }
    number = await call_http(_asgi(application), path="/number?value=7")
    assert json.loads(message_body(number[1])) == 7
    invalid = await call_http(
        _asgi(application),
        method="POST",
        path="/payload",
        body=b'{"value": "bad"}',
        headers=[(b"content-type", b"application/json")],
    )
    assert invalid[0]["status"] == 400
    assert "errors" in json.loads(message_body(invalid[1]))
    await application.close()


@pytest.mark.asyncio
async def test_guard_false_and_filter_precedence(call_http) -> None:
    class DenyGuard:
        async def can_activate(self, context) -> bool:
            return False

    class RouteFilter:
        async def catch(self, error, context):
            return PipelineResult.from_response(
                Response("route-filter", status_code=418)
            )

    class GlobalFilter:
        async def catch(self, error, context):
            return PipelineResult.from_response(
                Response("global-filter", status_code=419)
            )

    @controller()
    class Controller:
        @get("/denied")
        @use_guards("deny")
        @use_filters("route-filter")
        async def denied(self) -> str:
            return "not reached"

    @module(
        controllers=[Controller],
        providers=[
            ValueProvider("deny", DenyGuard()),
            ValueProvider("route-filter", RouteFilter()),
            ValueProvider("global-filter", GlobalFilter()),
        ],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile(
        pipeline=PipelineOptions(filters=("global-filter",)),
        adapter=StarletteAdapter(),
    )
    denied = await call_http(_asgi(application), path="/denied")
    assert denied[0]["status"] == 418
    missing = await call_http(_asgi(application), path="/missing")
    assert missing[0]["status"] == 419
    await application.close()


@pytest.mark.asyncio
async def test_filter_resolution_failure_falls_through_to_later_filter(
    caplog: pytest.LogCaptureFixture,
    call_http,
    message_headers,
) -> None:
    def broken_filter() -> object:
        raise RuntimeError(_SENSITIVE_EXCEPTION_TEXT)

    class GlobalFilter:
        async def catch(self, error, context):
            return PipelineResult.from_response(
                Response("global-filter", status_code=419)
            )

    @controller()
    class Controller:
        @get("/profiles/{handle}")
        @use_filter("broken-filter")
        async def failure(
            self,
            handle: Annotated[str, Path("handle")],
            cursor: Annotated[str, Query("cursor")],
        ) -> str:
            raise RuntimeError(f"{handle} {cursor} {_SENSITIVE_EXCEPTION_TEXT}")

    @module(
        controllers=[Controller],
        providers=[
            FactoryProvider(
                "broken-filter",
                broken_filter,
                scope=Scope.REQUEST,
            ),
            ValueProvider("global-filter", GlobalFilter()),
        ],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile(
        pipeline=PipelineOptions(filters=("global-filter",)),
        adapter=StarletteAdapter(),
    )
    with caplog.at_level(logging.ERROR):
        response = await call_http(
            _asgi(application),
            path="/profiles/sentinel-handle?cursor=cursor-secret-42",
            headers=[(b"x-request-id", b"caller-request-id-sentinel")],
        )
    await application.close()

    assert response[0]["status"] == 419
    assert (b"x-request-id", b"caller-request-id-sentinel") in message_headers(
        response[0]
    )
    records = [
        record for record in caplog.records if record.name.startswith("tori_py.")
    ]
    _assert_sanitized_http_records(
        records,
        ["tori_py.http.exception_filter_resolution_failed"],
    )


@pytest.mark.asyncio
async def test_http_fallback_logs_are_value_free_and_use_generated_event_ids(
    caplog: pytest.LogCaptureFixture,
    call_http,
    message_headers,
) -> None:
    class FailingFilter:
        async def catch(self, error, context):
            del error, context
            raise RuntimeError(_SENSITIVE_EXCEPTION_TEXT)

    @controller()
    class Controller:
        @get("/profiles/{handle}")
        @use_filter(FailingFilter())
        async def failure(
            self,
            handle: Annotated[str, Path("handle")],
            cursor: Annotated[str, Query("cursor")],
        ) -> None:
            raise RuntimeError(f"{handle} {cursor} {_SENSITIVE_EXCEPTION_TEXT}")

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    with caplog.at_level(logging.ERROR):
        response = await call_http(
            _asgi(application),
            path="/profiles/sentinel-handle?cursor=cursor-secret-42",
            headers=[(b"x-request-id", b"caller-request-id-sentinel")],
        )
    await application.close()

    assert response[0]["status"] == 500
    assert (b"x-request-id", b"caller-request-id-sentinel") in message_headers(
        response[0]
    )
    records = [
        record for record in caplog.records if record.name.startswith("tori_py.")
    ]
    _assert_sanitized_http_records(
        records,
        [
            "tori_py.http.exception_filter_failed",
            "tori_py.http.unhandled_exception",
        ],
    )


@pytest.mark.asyncio
async def test_exception_and_routing_render_fallback_logs_are_sanitized(
    caplog: pytest.LogCaptureFixture,
    call_http,
    message_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_encoding(*args, **kwargs):
        del args, kwargs
        raise RuntimeError(_SENSITIVE_EXCEPTION_TEXT)

    monkeypatch.setattr(routes_module, "_encode_pipeline_result", fail_encoding)

    @controller()
    class Controller:
        @get("/profiles/{handle}")
        async def failure(
            self,
            handle: Annotated[str, Path("handle")],
            cursor: Annotated[str, Query("cursor")],
        ) -> None:
            raise RuntimeError(f"{handle} {cursor} {_SENSITIVE_EXCEPTION_TEXT}")

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    headers = [(b"x-request-id", b"caller-request-id-sentinel")]
    with caplog.at_level(logging.ERROR):
        exception_response = await call_http(
            _asgi(application),
            path="/profiles/sentinel-handle?cursor=cursor-secret-42",
            headers=headers,
        )
        routing_response = await call_http(
            _asgi(application),
            path="/sentinel-handle?cursor=cursor-secret-42",
            headers=headers,
        )
    await application.close()

    assert exception_response[0]["status"] == 500
    assert routing_response[0]["status"] == 500
    for response in (exception_response, routing_response):
        assert (b"x-request-id", b"caller-request-id-sentinel") in message_headers(
            response[0]
        )
    records = [
        record for record in caplog.records if record.name.startswith("tori_py.")
    ]
    _assert_sanitized_http_records(
        records,
        [
            "tori_py.http.unhandled_exception",
            "tori_py.http.exception_response_failed",
            "tori_py.http.routing_response_failed",
        ],
    )


@pytest.mark.asyncio
async def test_failure_after_response_start_logs_only_a_sanitized_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingResponse(Response):
        async def __call__(self, scope, receive, send) -> None:
            del scope, receive
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                }
            )
            raise RuntimeError(_SENSITIVE_EXCEPTION_TEXT)

    @controller()
    class Controller:
        @get("/profiles/{handle}")
        async def failure(
            self,
            handle: Annotated[str, Path("handle")],
            cursor: Annotated[str, Query("cursor")],
        ) -> Response:
            del handle, cursor
            return FailingResponse()

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    incoming = iter(
        cast(
            list[Message],
            [
                {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }
            ],
        )
    )
    sent: list[Message] = []

    async def receive() -> Message:
        return next(incoming)

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
            "path": "/profiles/sentinel-handle",
            "raw_path": b"/profiles/sentinel-handle",
            "query_string": b"cursor=cursor-secret-42",
            "headers": [(b"x-request-id", b"caller-request-id-sentinel")],
            "client": ("test", 1),
            "server": ("test", 80),
        },
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="workflow-ref"):
            await _asgi(application)(scope, receive, send)
    await application.close()

    assert sent[0]["type"] == "http.response.start"
    assert (b"x-request-id", b"caller-request-id-sentinel") in cast(
        list[tuple[bytes, bytes]], sent[0]["headers"]
    )
    records = [
        record for record in caplog.records if record.name.startswith("tori_py.")
    ]
    _assert_sanitized_http_records(
        records,
        [
            "tori_py.http.unhandled_exception",
            "tori_py.http.response_transmission_failed",
        ],
    )


@pytest.mark.asyncio
async def test_emergency_renderer_failure_log_excludes_ambient_request_context(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @module()
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    adapter = application.get_adapter(StarletteAdapter)
    binder = cast(Any, adapter)._binder

    def fail_emergency(context) -> object:
        del context
        raise RuntimeError(_SENSITIVE_EXCEPTION_TEXT)

    monkeypatch.setattr(binder.pipeline.transport, "render_emergency", fail_emergency)
    with caplog.at_level(logging.ERROR):
        with use_log_context(request_id="caller-request-id-sentinel"):
            with pytest.raises(RuntimeError, match="workflow-ref"):
                binder.pipeline._render_emergency(cast(Any, object()))
    await application.close()

    records = [
        record for record in caplog.records if record.name.startswith("tori_py.")
    ]
    _assert_sanitized_http_records(
        records,
        ["tori_py.http.emergency_response_failed"],
    )


@pytest.mark.parametrize(
    "error",
    [
        ClientDisconnect(),
        asyncio.CancelledError(),
        KeyboardInterrupt(),
        SystemExit(),
    ],
)
@pytest.mark.asyncio
async def test_emergency_renderer_propagates_abort_and_process_control(
    caplog: pytest.LogCaptureFixture,
    error: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @module()
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    adapter = application.get_adapter(StarletteAdapter)
    binder = cast(Any, adapter)._binder

    def fail_emergency(context) -> object:
        del context
        raise error

    monkeypatch.setattr(binder.pipeline.transport, "render_emergency", fail_emergency)
    with caplog.at_level(logging.ERROR):
        with use_log_context(request_id="caller-request-id-sentinel"):
            with pytest.raises(BaseException) as raised:
                binder.pipeline._render_emergency(cast(Any, object()))
    await application.close()

    assert raised.value is error
    assert [
        record for record in caplog.records if record.name.startswith("tori_py.")
    ] == []


@pytest.mark.asyncio
async def test_raw_annotation_is_not_converted_without_validation_pipe(
    call_http,
    message_body,
) -> None:
    @controller()
    class Controller:
        @get("/raw")
        async def raw(self, value: Annotated[int, Query("value")]) -> object:
            return {"value": value, "type": type(value).__name__}

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    messages = await call_http(_asgi(application), path="/raw?value=7")
    assert json.loads(message_body(messages[1])) == {"value": "7", "type": "str"}
    await application.close()


@pytest.mark.asyncio
async def test_application_global_methods_reach_starlette_pipeline(
    call_http,
    message_body,
    message_headers,
) -> None:
    events: list[str] = []

    class InitialPipe:
        async def transform(self, value, metadata):
            events.append("initial-pipe")
            return f"{value}-initial"

    class AllowGuard:
        async def can_activate(self, context) -> bool:
            events.append("guard")
            return True

    class SuffixPipe:
        async def on_module_init(self) -> None:
            events.append("method-pipe-init")

        async def transform(self, value, metadata):
            events.append("method-pipe")
            return f"{value}-method"

        async def on_module_destroy(self) -> None:
            events.append("method-pipe-destroy")

    class RecordingInterceptor:
        async def intercept(self, context, next):
            events.append("interceptor-in")
            result = await next()
            events.append("interceptor-out")
            return result

    class GlobalFilter:
        async def catch(self, error, context):
            events.append(f"filter:{type(error).__name__}:{context.route_id}")
            if not isinstance(error, RuntimeError):
                return PipelineResult.from_response(
                    Response(status_code=error.status_code, headers=error.headers)
                )
            return PipelineResult.from_response(
                Response("global-filter", status_code=419)
            )

    @controller()
    class Controller:
        @get("/value")
        async def value(self, value: Annotated[str, Query("value")]) -> str:
            events.append("handler")
            return value

        @get("/failure")
        async def failure(self) -> str:
            events.append("failure-handler")
            raise RuntimeError("failure")

    @module(
        controllers=[Controller],
        providers=[
            ValueProvider("allow", AllowGuard()),
            ClassProvider(SuffixPipe, SuffixPipe),
        ],
    )
    class Root:
        pass

    application = await NestApplication.create(
        Root,
        pipeline=PipelineOptions(pipes=(InitialPipe(),)),
        adapter=StarletteAdapter(),
    )
    application.use_global_guard("allow").use_global_pipe(
        SuffixPipe
    ).use_global_interceptor(RecordingInterceptor()).use_global_filter(GlobalFilter())
    await application.start()
    assert events == ["method-pipe-init"]
    events.clear()

    value = await call_http(_asgi(application), path="/value?value=raw")
    assert json.loads(message_body(value[1])) == "raw-initial-method"
    assert events == [
        "guard",
        "initial-pipe",
        "method-pipe",
        "interceptor-in",
        "handler",
        "interceptor-out",
    ]

    events.clear()
    failure = await call_http(_asgi(application), path="/failure")
    assert failure[0]["status"] == 419
    assert events == [
        "guard",
        "interceptor-in",
        "failure-handler",
        "filter:RuntimeError:GET /failure",
    ]

    events.clear()
    missing = await call_http(_asgi(application), path="/missing")
    assert missing[0]["status"] == 404
    assert events == ["filter:HttpException:None"]

    events.clear()
    wrong_method = await call_http(_asgi(application), method="POST", path="/value")
    assert wrong_method[0]["status"] == 405
    allow = dict(message_headers(wrong_method[0]))[b"allow"].decode().split(", ")
    assert set(allow) == {"GET", "HEAD"}
    assert events == ["filter:HttpException:None"]
    events.clear()
    await application.shutdown()
    assert events == ["method-pipe-destroy"]


@pytest.mark.asyncio
async def test_pipeline_visibility_fails_before_application_start() -> None:
    events: list[str] = []

    @module()
    class Root:
        def __init__(self) -> None:
            events.append("constructed")

    with pytest.raises(BootstrapError, match="pipeline provider"):
        await TestingModule.create(Root).compile(
            pipeline=PipelineOptions(middleware=("missing",)),
            adapter=StarletteAdapter(),
        )
    assert events == []


@pytest.mark.asyncio
async def test_middleware_next_is_one_shot_and_short_circuit_is_allowed(
    call_http,
) -> None:
    class DoubleNext:
        async def handle(self, context, next):
            await next()
            await next()

    class ShortCircuit:
        async def handle(self, context, next):
            del next
            return PipelineResult.from_response(Response("short", status_code=202))

    class PortableShortCircuit:
        async def handle(self, context, next):
            del context, next
            return PipelineResult.from_response(
                HttpResponse(
                    b"portable-short",
                    status_code=203,
                    headers={"content-type": "text/plain"},
                )
            )

    @controller()
    class Controller:
        @get("/double")
        @use_middleware("double")
        async def double(self) -> str:
            return "not reached"

        @get("/short")
        @use_middleware("short")
        async def short(self) -> str:
            return "not reached"

        @get("/portable-short")
        @use_middleware("portable-short")
        async def portable_short(self) -> str:
            return "not reached"

    @module(
        controllers=[Controller],
        providers=[
            ValueProvider("double", DoubleNext()),
            ValueProvider("short", ShortCircuit()),
            ValueProvider("portable-short", PortableShortCircuit()),
        ],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    double = await call_http(_asgi(application), path="/double")
    assert double[0]["status"] == 500
    short = await call_http(_asgi(application), path="/short")
    assert short[0]["status"] == 202
    portable_short = await call_http(_asgi(application), path="/portable-short")
    assert portable_short[0]["status"] == 203
    assert portable_short[1]["body"] == b"portable-short"
    await application.close()


@pytest.mark.asyncio
async def test_enhancer_classes_are_implicit_injectable_providers(
    call_http,
    message_body,
) -> None:
    events: list[str] = []

    class Dependency:
        message = "injected"

    class ClassGuard:
        def __init__(self, dependency: Dependency) -> None:
            self.dependency = dependency

        async def can_activate(self, context) -> bool:
            events.append(f"guard:{self.dependency.message}")
            return True

    class ClassPipe:
        async def transform(self, value, metadata):
            events.append("pipe")
            return f"{value}-piped"

    class ClassInterceptor:
        async def intercept(self, context, next):
            events.append("interceptor-in")
            result = await next()
            events.append("interceptor-out")
            return result

    class ClassFilter:
        async def catch(self, error, context):
            events.append(f"filter:{error}")
            return Response("class-filter", status_code=418)

    @controller()
    class Controller:
        @get("/class")
        @use_guard(ClassGuard)
        @use_pipe(ClassPipe)
        @use_interceptor(ClassInterceptor)
        async def enhanced(self, value: Annotated[str, Query("value")]) -> str:
            events.append("handler")
            return value

        @get("/class-error")
        @use_filter(ClassFilter)
        async def failed(self) -> str:
            raise RuntimeError("boom")

    @module(
        controllers=[Controller],
        providers=[ClassProvider(Dependency)],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    enhanced = await call_http(_asgi(application), path="/class?value=raw")
    assert json.loads(message_body(enhanced[1])) == "raw-piped"
    failed = await call_http(_asgi(application), path="/class-error")
    assert failed[0]["status"] == 418
    assert events == [
        "guard:injected",
        "pipe",
        "interceptor-in",
        "handler",
        "interceptor-out",
        "filter:boom",
    ]
    await application.close()


@pytest.mark.asyncio
async def test_enhancer_instances_are_shared_and_externally_owned(
    call_http,
    message_body,
) -> None:
    class InstanceGuard:
        def __init__(self) -> None:
            self.calls = 0

        async def can_activate(self, context) -> bool:
            self.calls += 1
            return True

    class InstancePipe:
        async def transform(self, value, metadata):
            return f"{value}-instance"

    class InstanceInterceptor:
        def __init__(self) -> None:
            self.calls = 0

        async def intercept(self, context, next):
            self.calls += 1
            return await next()

    class InstanceFilter:
        def __init__(self) -> None:
            self.calls = 0

        async def catch(self, error, context):
            self.calls += 1
            return Response("instance-filter", status_code=419)

    guard = InstanceGuard()
    pipe = InstancePipe()
    interceptor = InstanceInterceptor()
    filter_ = InstanceFilter()

    @controller()
    class Controller:
        @get("/instance")
        @use_guard(guard)
        @use_pipe(pipe)
        @use_interceptor(interceptor)
        async def enhanced(self, value: Annotated[str, Query("value")]) -> str:
            return value

        @get("/instance-error")
        @use_filter(filter_)
        async def failed(self) -> str:
            raise RuntimeError("boom")

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    first = await call_http(_asgi(application), path="/instance?value=one")
    second = await call_http(_asgi(application), path="/instance?value=two")
    failed = await call_http(_asgi(application), path="/instance-error")
    assert json.loads(message_body(first[1])) == "one-instance"
    assert json.loads(message_body(second[1])) == "two-instance"
    assert failed[0]["status"] == 419
    assert guard.calls == 2
    assert interceptor.calls == 2
    assert filter_.calls == 1
    await application.close()


@pytest.mark.asyncio
async def test_explicit_provider_takes_precedence_for_global_enhancer_class(
    call_http,
) -> None:
    class GlobalGuard:
        async def can_activate(self, context) -> bool:
            return True

    class DenyGuard:
        async def can_activate(self, context) -> bool:
            return False

    @controller()
    class Controller:
        @get("/global-class")
        async def endpoint(self) -> str:
            return "allowed"

    @module(
        providers=[ValueProvider(GlobalGuard, DenyGuard())],
        exports=[GlobalGuard],
    )
    class GuardsModule:
        pass

    @module(imports=[GuardsModule], controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(
        pipeline=PipelineOptions(guards=(GlobalGuard,)),
        adapter=StarletteAdapter(),
    )
    response = await call_http(_asgi(application), path="/global-class")
    assert response[0]["status"] == 403
    await application.close()


@pytest.mark.asyncio
async def test_global_enhancer_class_uses_effective_replaced_root(call_http) -> None:
    class GlobalGuard:
        async def can_activate(self, context) -> bool:
            return True

    @controller()
    class Controller:
        @get("/replacement")
        async def endpoint(self) -> str:
            return "replacement"

    class DynamicRoot:
        pass

    descriptor = DeferredModule(DynamicRoot, "root", lambda: ModuleSpec())

    @module(controllers=[Controller])
    class Replacement:
        pass

    builder = TestingModule.create(descriptor)
    builder.replace_module(descriptor, Replacement)
    application = await builder.compile(
        pipeline=PipelineOptions(guards=(GlobalGuard,)),
        adapter=StarletteAdapter(),
    )
    response = await call_http(_asgi(application), path="/replacement")
    assert response[0]["status"] == 200
    await application.close()


@pytest.mark.asyncio
async def test_implicit_enhancer_class_can_be_exported(call_http) -> None:
    class ExportedGuard:
        async def can_activate(self, context) -> bool:
            return True

    @controller()
    class Controller:
        @get("/exported")
        @use_guard(ExportedGuard)
        async def endpoint(self) -> str:
            return "exported"

    @module(controllers=[Controller], exports=[ExportedGuard])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    response = await call_http(_asgi(application), path="/exported")
    assert response[0]["status"] == 200
    await application.close()


@pytest.mark.asyncio
async def test_non_route_enhancer_metadata_does_not_register_provider(
    call_http,
) -> None:
    class MissingDependency:
        pass

    class UnusedGuard:
        def __init__(self, missing: MissingDependency) -> None:
            self.missing = missing

        async def can_activate(self, context) -> bool:
            return True

    @controller()
    class Controller:
        @use_guard(UnusedGuard)
        async def helper(self) -> None:
            pass

        @get("/without-helper")
        async def endpoint(self) -> str:
            return "ok"

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    response = await call_http(_asgi(application), path="/without-helper")
    assert response[0]["status"] == 200
    await application.close()


@pytest.mark.asyncio
async def test_explicit_request_scoped_guard_is_not_replaced_by_fallback(
    call_http,
) -> None:
    instances: list[RequestGuard] = []

    class RequestGuard:
        def __init__(self) -> None:
            instances.append(self)

        async def can_activate(self, context) -> bool:
            return True

    @controller()
    class Controller:
        @get("/request-guard")
        @use_guard(RequestGuard)
        async def endpoint(self) -> str:
            return "allowed"

    @module(
        controllers=[Controller],
        providers=[ClassProvider(RequestGuard, scope=Scope.REQUEST)],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    first = await call_http(_asgi(application), path="/request-guard")
    second = await call_http(_asgi(application), path="/request-guard")
    assert first[0]["status"] == 200
    assert second[0]["status"] == 200
    assert len(instances) == 2
    assert instances[0] is not instances[1]
    await application.close()


@pytest.mark.asyncio
async def test_global_enhancer_instances_are_shared_and_externally_owned(
    call_http,
    message_body,
) -> None:
    class GlobalGuard:
        def __init__(self) -> None:
            self.calls = 0

        async def can_activate(self, context) -> bool:
            self.calls += 1
            return True

    class GlobalPipe:
        def __init__(self) -> None:
            self.calls = 0

        async def transform(self, value, metadata):
            self.calls += 1
            return f"{value}-global"

    class GlobalInterceptor:
        def __init__(self) -> None:
            self.calls = 0

        async def intercept(self, context, next):
            self.calls += 1
            return await next()

    class GlobalFilter:
        def __init__(self) -> None:
            self.calls = 0

        async def catch(self, error, context):
            self.calls += 1
            return Response("global-instance-filter", status_code=420)

    guard = GlobalGuard()
    pipe = GlobalPipe()
    interceptor = GlobalInterceptor()
    filter_ = GlobalFilter()

    @controller()
    class Controller:
        @get("/global-instance")
        async def endpoint(self, value: Annotated[str, Query("value")]) -> str:
            return value

        @get("/global-instance-error")
        async def failed(self) -> str:
            raise RuntimeError("boom")

    @module(controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(
        pipeline=PipelineOptions(
            guards=(guard,),
            pipes=(pipe,),
            interceptors=(interceptor,),
            filters=(filter_,),
        ),
        adapter=StarletteAdapter(),
    )
    first = await call_http(_asgi(application), path="/global-instance?value=one")
    second = await call_http(_asgi(application), path="/global-instance?value=two")
    failed = await call_http(_asgi(application), path="/global-instance-error")
    assert json.loads(message_body(first[1])) == "one-global"
    assert json.loads(message_body(second[1])) == "two-global"
    assert failed[0]["status"] == 420
    assert guard.calls == 3
    assert pipe.calls == 2
    assert interceptor.calls == 3
    assert filter_.calls == 1
    await application.close()


@pytest.mark.asyncio
async def test_global_module_export_takes_precedence_for_global_enhancer_class(
    call_http,
) -> None:
    class GlobalGuard:
        async def can_activate(self, context) -> bool:
            return True

    class DenyGuard:
        async def can_activate(self, context) -> bool:
            return False

    @controller()
    class Controller:
        @get("/global-module")
        async def endpoint(self) -> str:
            return "allowed"

    @module(
        providers=[ValueProvider(GlobalGuard, DenyGuard())],
        exports=[GlobalGuard],
        global_=True,
    )
    class GlobalGuardsModule:
        pass

    @module(imports=[GlobalGuardsModule], controllers=[Controller])
    class Root:
        pass

    application = await TestingModule.create(Root).compile(
        pipeline=PipelineOptions(guards=(GlobalGuard,)),
        adapter=StarletteAdapter(),
    )
    response = await call_http(_asgi(application), path="/global-module")
    assert response[0]["status"] == 403
    await application.close()


def test_direct_enhancer_instances_are_validated_by_kind() -> None:
    invalid = cast(Any, object())
    with pytest.raises(BootstrapError, match="can_activate"):
        use_guard(invalid)
    with pytest.raises(BootstrapError, match="provider token"):
        use_middleware(invalid)
