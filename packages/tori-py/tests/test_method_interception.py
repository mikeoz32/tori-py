import asyncio
from typing import Annotated, cast

import pytest
from tori_py import (
    AliasProvider,
    BootstrapError,
    ClassProvider,
    FactoryProvider,
    Inject,
    MethodInvocationContext,
    PipelineStateError,
    Scope,
    WorkScopeFactory,
    compile_graph,
    injectable,
    module,
    use_method_interceptor,
    use_method_interceptors,
)
from tori_py.core.errors import ScopeError
from tori_py.core.runtime import ApplicationKernel


@pytest.mark.asyncio
async def test_opt_in_proxies_resolve_method_interceptors_in_the_active_scope() -> None:
    stamps: list[RequestStamp] = []

    class RequestStamp:
        def __init__(self) -> None:
            self.value = len(stamps) + 1
            stamps.append(cast(RequestStamp, self))

    calls: list[str] = []

    class TraceInterceptor:
        def __init__(
            self,
            stamp: Annotated[RequestStamp, Inject(RequestStamp)],
        ) -> None:
            self.stamp = stamp

        async def intercept(
            self,
            context: MethodInvocationContext,
            next,
        ) -> object:
            calls.append(context.method_name)
            assert await context.resolver.resolve(RequestStamp) is self.stamp
            return f"{await next()}:{self.stamp.value}"

    @injectable(proxy=True)
    class DecoratedService:
        @use_method_interceptors("trace")
        async def execute(self) -> str:
            return "decorated"

        async def plain(self) -> str:
            return "plain"

    class ExplicitService:
        @use_method_interceptors("trace")
        async def execute(self) -> str:
            return "explicit"

    class WorkRunner:
        def __init__(self, scopes: WorkScopeFactory) -> None:
            self.scopes = scopes

        async def execute(self) -> str:
            async def invoke(resolver) -> str:
                service = cast(
                    DecoratedService,
                    await resolver.resolve(DecoratedService),
                )
                return await service.execute()

            return await self.scopes.run(invoke)

    @module(
        providers=[
            DecoratedService,
            ClassProvider("explicit", ExplicitService, proxy=True),
            ClassProvider(RequestStamp, scope=Scope.REQUEST),
            ClassProvider("trace", TraceInterceptor, scope=Scope.REQUEST),
            ClassProvider(WorkRunner),
        ]
    )
    class Root:
        pass

    graph = await compile_graph(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()
    resolver = kernel.resolver(graph.root)
    decorated = cast(DecoratedService, await resolver.resolve(DecoratedService))
    explicit = cast(ExplicitService, await resolver.resolve("explicit"))
    work_runner = cast(WorkRunner, await resolver.resolve(WorkRunner))

    assert isinstance(decorated, DecoratedService)
    assert isinstance(explicit, ExplicitService)
    assert await decorated.plain() == "plain"
    with pytest.raises(ScopeError, match="active request or work scope"):
        await decorated.execute()

    async with kernel.request_scope(graph.root):
        assert await decorated.execute() == "decorated:1"
        assert await explicit.execute() == "explicit:1"
        child = asyncio.create_task(decorated.execute())
        with pytest.raises(ScopeError, match="owner task"):
            await child
    async with kernel.request_scope(graph.root):
        assert await decorated.execute() == "decorated:2"
    assert await work_runner.execute() == "decorated:3"

    assert calls == ["execute", "execute", "execute", "execute"]
    await kernel.shutdown()


@pytest.mark.asyncio
async def test_interceptor_providers_resolve_lazily_inside_the_chain() -> None:
    inner_constructions = 0

    class OuterInterceptor:
        async def intercept(self, context, next) -> object:
            if context.method_name == "short_circuit":
                return "short-circuited"
            try:
                return await next()
            except LookupError:
                return "inner resolution handled"

    def create_inner_interceptor() -> object:
        nonlocal inner_constructions
        inner_constructions += 1
        raise LookupError("inner interceptor construction failed")

    @injectable(proxy=True)
    class Service:
        @use_method_interceptors(OuterInterceptor(), "inner")
        async def short_circuit(self) -> str:
            return "unreachable"

        @use_method_interceptors(OuterInterceptor(), "inner")
        async def catch_inner_failure(self) -> str:
            return "unreachable"

    @module(
        providers=[
            Service,
            FactoryProvider("inner", create_inner_interceptor, scope=Scope.REQUEST),
        ]
    )
    class Root:
        pass

    graph = await compile_graph(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()
    service = cast(Service, await kernel.resolver(graph.root).resolve(Service))

    async with kernel.request_scope(graph.root):
        assert await service.short_circuit() == "short-circuited"
        assert inner_constructions == 0
        assert await service.catch_inner_failure() == "inner resolution handled"
        assert inner_constructions == 1

    await kernel.shutdown()


@pytest.mark.asyncio
async def test_provider_proxy_cannot_use_another_container_scope() -> None:
    class TraceInterceptor:
        async def intercept(self, context, next) -> object:
            return await next()

    @injectable(proxy=True)
    class Service:
        @use_method_interceptors(TraceInterceptor())
        async def execute(self) -> str:
            return "ok"

    @module(providers=[Service])
    class Root:
        pass

    graph = await compile_graph(Root)
    first_kernel = ApplicationKernel(graph)
    second_kernel = ApplicationKernel(graph)
    await first_kernel.start()
    await second_kernel.start()
    first_service = cast(
        Service,
        await first_kernel.resolver(graph.root).resolve(Service),
    )

    async with second_kernel.request_scope(graph.root):
        with pytest.raises(ScopeError, match="active request or work scope"):
            await first_service.execute()

    await first_kernel.shutdown()
    await second_kernel.shutdown()


@pytest.mark.asyncio
async def test_proxy_self_invocation_does_not_reenter_method_interceptors() -> None:
    calls: list[str] = []

    class TraceInterceptor:
        async def intercept(
            self,
            context: MethodInvocationContext,
            next,
        ) -> object:
            calls.append(context.method_name)
            return f"{await next()}:{context.method_name}"

    @injectable(proxy=True)
    class Service:
        @use_method_interceptors(TraceInterceptor())
        async def outer(self) -> str:
            return await self.inner()

        @use_method_interceptors(TraceInterceptor())
        async def inner(self) -> str:
            return "inner"

    @module(providers=[Service])
    class Root:
        pass

    graph = await compile_graph(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()
    service = cast(Service, await kernel.resolver(graph.root).resolve(Service))

    async with kernel.request_scope(graph.root):
        assert await service.outer() == "inner:outer"

    assert calls == ["outer"]
    await kernel.shutdown()


@pytest.mark.asyncio
async def test_stacked_method_interceptors_run_outermost_first() -> None:
    events: list[str] = []

    class OuterInterceptor:
        async def intercept(self, context, next) -> object:
            del context
            events.append("outer-in")
            result = await next()
            events.append("outer-out")
            return result

    class InnerInterceptor:
        async def intercept(self, context, next) -> object:
            del context
            events.append("inner-in")
            result = await next()
            events.append("inner-out")
            return result

    @injectable(proxy=True)
    class Service:
        @use_method_interceptors(OuterInterceptor())
        @use_method_interceptors(InnerInterceptor())
        async def execute(self) -> str:
            events.append("method")
            return "done"

    @module(providers=[Service])
    class Root:
        pass

    graph = await compile_graph(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()
    service = cast(Service, await kernel.resolver(graph.root).resolve(Service))

    async with kernel.request_scope(graph.root):
        assert await service.execute() == "done"

    assert events == [
        "outer-in",
        "inner-in",
        "method",
        "inner-out",
        "outer-out",
    ]
    await kernel.shutdown()


@pytest.mark.asyncio
async def test_method_interceptors_support_both_class_and_static_method_orders() -> (
    None
):
    calls: list[str] = []

    class TraceInterceptor:
        async def intercept(self, context, next) -> object:
            calls.append(context.method_name)
            return await next()

    @injectable(proxy=True)
    class Service:
        @use_method_interceptor(TraceInterceptor())
        @classmethod
        async def class_outer(cls) -> str:
            return cls.__name__

        @classmethod
        @use_method_interceptor(TraceInterceptor())
        async def class_inner(cls) -> str:
            return cls.__name__

        @use_method_interceptor(TraceInterceptor())
        @staticmethod
        async def static_outer() -> str:
            return "outer"

        @staticmethod
        @use_method_interceptor(TraceInterceptor())
        async def static_inner() -> str:
            return "inner"

    @module(providers=[Service])
    class Root:
        pass

    graph = await compile_graph(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()
    service = cast(Service, await kernel.resolver(graph.root).resolve(Service))

    async with kernel.request_scope(graph.root):
        assert await service.class_outer() == "Service"
        assert await service.class_inner() == "Service"
        assert await service.static_outer() == "outer"
        assert await service.static_inner() == "inner"

    assert calls == ["class_outer", "class_inner", "static_outer", "static_inner"]
    await kernel.shutdown()


@pytest.mark.asyncio
async def test_alias_to_proxy_preserves_advice_and_inherited_method_override() -> None:
    calls: list[str] = []

    class TraceInterceptor:
        async def intercept(self, context, next) -> object:
            calls.append(context.method_name)
            return await next()

    class BaseService:
        @use_method_interceptors(TraceInterceptor())
        async def inherited(self) -> str:
            return "base"

        @use_method_interceptors(TraceInterceptor())
        async def overridden(self) -> str:
            return "base override"

    @injectable(proxy=True)
    class Service(BaseService):
        async def overridden(self) -> str:
            return "derived override"

    @module(providers=[Service, AliasProvider("service.alias", Service)])
    class Root:
        pass

    graph = await compile_graph(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()
    resolver = kernel.resolver(graph.root)
    service = cast(Service, await resolver.resolve(Service))
    alias = cast(Service, await resolver.resolve("service.alias"))

    assert service is alias
    async with kernel.request_scope(graph.root):
        assert await alias.inherited() == "base"
        assert await service.overridden() == "derived override"

    assert calls == ["inherited"]
    await kernel.shutdown()


@pytest.mark.parametrize(
    ("provider_scope", "same_instance"),
    ((Scope.REQUEST, True), (Scope.TRANSIENT, False)),
    ids=("request", "transient"),
)
@pytest.mark.asyncio
async def test_proxied_services_preserve_request_and_transient_lifetimes(
    provider_scope: Scope,
    same_instance: bool,
) -> None:
    class TraceInterceptor:
        async def intercept(self, context, next) -> object:
            return await next()

    class Service:
        @use_method_interceptors(TraceInterceptor())
        async def identity(self) -> int:
            return id(self)

    @module(
        providers=[
            ClassProvider(Service, scope=provider_scope, proxy=True),
        ]
    )
    class Root:
        pass

    graph = await compile_graph(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()

    async with kernel.request_scope(graph.root) as resolver:
        first = cast(Service, await resolver.resolve(Service))
        second = cast(Service, await resolver.resolve(Service))
        assert (first is second) is same_instance
        assert (await first.identity() == await second.identity()) is same_instance

    await kernel.shutdown()


@pytest.mark.asyncio
async def test_managed_proxy_cleanup_after_error_and_cancellation() -> None:
    events: list[str] = []
    started = asyncio.Event()

    class TraceInterceptor:
        async def intercept(self, context, next) -> object:
            events.append(f"{context.method_name}:before")
            try:
                return await next()
            finally:
                events.append(f"{context.method_name}:after")

    @injectable(scope=Scope.REQUEST, proxy=True)
    class ManagedService:
        async def __aenter__(self):
            events.append("resource:enter")
            return self

        async def __aexit__(self, *exc_info: object) -> None:
            del exc_info
            events.append("resource:exit")

        @use_method_interceptors(TraceInterceptor())
        async def fail(self) -> None:
            events.append("method:fail")
            raise ValueError("expected")

        @use_method_interceptors(TraceInterceptor())
        async def wait(self) -> None:
            events.append("method:wait")
            started.set()
            await asyncio.Event().wait()

    @module(providers=[ManagedService])
    class Root:
        pass

    graph = await compile_graph(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()

    with pytest.raises(ValueError, match="expected"):
        async with kernel.request_scope(graph.root) as scoped:
            service = cast(ManagedService, await scoped.resolve(ManagedService))
            await service.fail()

    assert events == [
        "resource:enter",
        "fail:before",
        "method:fail",
        "fail:after",
        "resource:exit",
    ]

    events.clear()
    task = asyncio.current_task()
    assert task is not None
    asyncio.get_running_loop().call_soon(task.cancel)
    with pytest.raises(asyncio.CancelledError):
        async with kernel.request_scope(graph.root) as scoped:
            service = cast(ManagedService, await scoped.resolve(ManagedService))
            await service.wait()

    assert started.is_set()
    assert events == [
        "resource:enter",
        "wait:before",
        "method:wait",
        "wait:after",
        "resource:exit",
    ]
    await kernel.shutdown()


@pytest.mark.asyncio
async def test_method_interceptor_next_can_only_be_called_once() -> None:
    calls: list[str] = []

    class DoubleNextInterceptor:
        async def intercept(self, context, next) -> object:
            del context
            await next()
            return await next()

    @injectable(proxy=True)
    class Service:
        @use_method_interceptors(DoubleNextInterceptor())
        async def execute(self) -> str:
            calls.append("method")
            return "done"

    @module(providers=[Service])
    class Root:
        pass

    graph = await compile_graph(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()
    service = cast(Service, await kernel.resolver(graph.root).resolve(Service))

    async with kernel.request_scope(graph.root):
        with pytest.raises(PipelineStateError, match="called twice"):
            await service.execute()

    assert calls == ["method"]
    await kernel.shutdown()


@pytest.mark.asyncio
async def test_method_interceptors_require_proxy_opt_in() -> None:
    class Service:
        @use_method_interceptors("trace")
        async def execute(self) -> None:
            return None

    @module(providers=[ClassProvider(Service)])
    class Root:
        pass

    with pytest.raises(BootstrapError, match="proxy=True") as captured:
        await compile_graph(Root)

    assert captured.value.diagnostic_code == "provider.invalid_declaration"


@pytest.mark.asyncio
async def test_method_interceptor_tokens_are_validated_during_compilation() -> None:
    @injectable(proxy=True)
    class Service:
        @use_method_interceptors("missing")
        async def execute(self) -> None:
            return None

    @module(providers=[Service])
    class Root:
        pass

    with pytest.raises(BootstrapError, match="not visible") as captured:
        await compile_graph(Root)

    assert captured.value.diagnostic_code == "provider.unresolved"


@pytest.mark.asyncio
async def test_sync_methods_cannot_bind_method_interceptors() -> None:
    class SyncService:
        @use_method_interceptors("trace")
        def execute(self) -> None:
            return None

    @module(
        providers=[
            ClassProvider(SyncService, proxy=True),
            ClassProvider("trace", object),
        ]
    )
    class Root:
        pass

    with pytest.raises(BootstrapError, match="public async methods") as captured:
        await compile_graph(Root)

    assert captured.value.diagnostic_code == "provider.invalid_declaration"
