import asyncio
from typing import Annotated, cast

import pytest
from tori_py import (
    BootstrapError,
    ClassProvider,
    Inject,
    MethodInvocationContext,
    PipelineStateError,
    Scope,
    WorkScopeFactory,
    compile_graph,
    injectable,
    module,
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
