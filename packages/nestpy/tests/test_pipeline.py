import json
from typing import Annotated, Any, cast

import msgspec
import pytest
from nestpy import (
    Body,
    BootstrapError,
    ClassProvider,
    Context,
    DeferredModule,
    Inject,
    ModuleSpec,
    PipelineResult,
    Query,
    Scope,
    StarletteOptions,
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

    application = await TestingModule.create(Root).compile()
    enhanced = await call_http(application.asgi, path="/class?value=raw")
    assert json.loads(message_body(enhanced[1])) == "raw-piped"
    failed = await call_http(application.asgi, path="/class-error")
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

    application = await TestingModule.create(Root).compile()
    first = await call_http(application.asgi, path="/instance?value=one")
    second = await call_http(application.asgi, path="/instance?value=two")
    failed = await call_http(application.asgi, path="/instance-error")
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
        http=StarletteOptions(guards=(GlobalGuard,))
    )
    response = await call_http(application.asgi, path="/global-class")
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
    application = await builder.compile(http=StarletteOptions(guards=(GlobalGuard,)))
    response = await call_http(application.asgi, path="/replacement")
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

    application = await TestingModule.create(Root).compile()
    response = await call_http(application.asgi, path="/exported")
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

    application = await TestingModule.create(Root).compile()
    response = await call_http(application.asgi, path="/without-helper")
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

    application = await TestingModule.create(Root).compile()
    first = await call_http(application.asgi, path="/request-guard")
    second = await call_http(application.asgi, path="/request-guard")
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
        http=StarletteOptions(
            guards=(guard,),
            pipes=(pipe,),
            interceptors=(interceptor,),
            filters=(filter_,),
        )
    )
    first = await call_http(application.asgi, path="/global-instance?value=one")
    second = await call_http(application.asgi, path="/global-instance?value=two")
    failed = await call_http(application.asgi, path="/global-instance-error")
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
        http=StarletteOptions(guards=(GlobalGuard,))
    )
    response = await call_http(application.asgi, path="/global-module")
    assert response[0]["status"] == 403
    await application.close()


def test_direct_enhancer_instances_are_validated_by_kind() -> None:
    invalid = cast(Any, object())
    with pytest.raises(BootstrapError, match="can_activate"):
        use_guard(invalid)
    with pytest.raises(BootstrapError, match="provider token"):
        use_middleware(invalid)
