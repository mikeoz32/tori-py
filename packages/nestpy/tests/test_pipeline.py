import json
from typing import Annotated

import msgspec
import pytest
from nestpy import (
    Body,
    BootstrapError,
    ClassProvider,
    Context,
    Inject,
    PipelineResult,
    Query,
    StarletteOptions,
    ValueProvider,
    controller,
    get,
    module,
    post,
    use_filters,
    use_guards,
    use_interceptors,
    use_middleware,
    use_pipes,
)
from nestpy.starlette import RequestContext
from nestpy.testing import TestingModule
from starlette.responses import Response


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

    options = StarletteOptions(
        middleware=("global-middleware",),
        guards=("global-guard",),
        pipes=("global-pipe",),
        interceptors=("global-interceptor",),
    )
    application = await TestingModule.create(Root).compile(http=options)
    messages = await call_http(application.asgi, path="/pipeline?value=raw")
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
            from nestpy.starlette.pipeline import MsgspecValidationPipe

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
        http=StarletteOptions(pipes=("validation",))
    )
    messages = await call_http(
        application.asgi,
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
    number = await call_http(application.asgi, path="/number?value=7")
    assert json.loads(message_body(number[1])) == 7
    invalid = await call_http(
        application.asgi,
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
        http=StarletteOptions(filters=("global-filter",))
    )
    denied = await call_http(application.asgi, path="/denied")
    assert denied[0]["status"] == 418
    missing = await call_http(application.asgi, path="/missing")
    assert missing[0]["status"] == 419
    await application.close()


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

    application = await TestingModule.create(Root).compile()
    messages = await call_http(application.asgi, path="/raw?value=7")
    assert json.loads(message_body(messages[1])) == {"value": "7", "type": "str"}
    await application.close()


@pytest.mark.asyncio
async def test_pipeline_visibility_fails_before_application_start() -> None:
    events: list[str] = []

    @module()
    class Root:
        def __init__(self) -> None:
            events.append("constructed")

    with pytest.raises(BootstrapError, match="pipeline provider"):
        await TestingModule.create(Root).compile(
            http=StarletteOptions(middleware=("missing",))
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

    @module(
        controllers=[Controller],
        providers=[
            ValueProvider("double", DoubleNext()),
            ValueProvider("short", ShortCircuit()),
        ],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    double = await call_http(application.asgi, path="/double")
    assert double[0]["status"] == 500
    short = await call_http(application.asgi, path="/short")
    assert short[0]["status"] == 202
    await application.close()
