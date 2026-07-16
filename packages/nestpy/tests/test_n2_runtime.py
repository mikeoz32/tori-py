import asyncio
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Annotated

import pytest
from nestpy import (
    AliasProvider,
    ApplicationOptions,
    ApplicationStateError,
    ClassProvider,
    FactoryProvider,
    Inject,
    LifecycleError,
    Scope,
    ScopeClosedError,
    ValueProvider,
    compile_graph,
    module,
)
from nestpy.core.runtime import (
    ApplicationKernel,
    ApplicationState,
    Container,
    RequestScope,
)


async def graph_for(root: type[object]):
    return await compile_graph(root)


@pytest.mark.asyncio
async def test_value_singleton_request_cache_transient_and_alias_identity() -> None:
    class RequestValue:
        pass

    class TransientValue:
        pass

    @module(
        providers=[
            ValueProvider("none", None),
            ValueProvider("value", object()),
            ClassProvider(RequestValue, scope=Scope.REQUEST),
            ClassProvider(TransientValue, scope=Scope.TRANSIENT),
            AliasProvider("alias", "value"),
        ]
    )
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)
    resolver = container.resolver(graph.root)
    assert await resolver.resolve("none") is None
    assert await resolver.resolve("none") is None
    value = await resolver.resolve("value")
    assert await resolver.resolve("alias") is value

    async with RequestScope(container, graph.root) as request:
        request_value = await request.resolve(RequestValue)
        assert await request.resolve(RequestValue) is request_value
        assert await request.resolve(TransientValue) is not await request.resolve(
            TransientValue
        )

    await container.close()


@pytest.mark.asyncio
async def test_concurrent_request_resolution_shares_one_inflight_creation() -> None:
    created = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def make_value() -> object:
        nonlocal created
        created += 1
        started.set()
        await release.wait()
        return object()

    @module(providers=[FactoryProvider("request", make_value, scope=Scope.REQUEST)])
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)
    async with RequestScope(container, graph.root) as resolver:
        first = asyncio.create_task(resolver.resolve("request"))
        second = asyncio.create_task(resolver.resolve("request"))
        await started.wait()
        assert created == 1
        release.set()
        assert await first is await second
    await container.close()


@pytest.mark.asyncio
async def test_async_resources_enter_and_exit_lifo() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def first() -> AsyncIterator[str]:
        events.append("first-enter")
        yield "first"
        events.append("first-exit")

    @asynccontextmanager
    async def second() -> AsyncIterator[str]:
        events.append("second-enter")
        yield "second"
        events.append("second-exit")

    @module(
        providers=[
            FactoryProvider("first", first),
            FactoryProvider("second", second),
        ]
    )
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)
    resolver = container.resolver(graph.root)
    assert await resolver.resolve("first") == "first"
    assert await resolver.resolve("second") == "second"
    await container.close()
    assert events == [
        "first-enter",
        "second-enter",
        "second-exit",
        "first-exit",
    ]


@pytest.mark.asyncio
async def test_managed_value_enters_but_unmanaged_value_does_not() -> None:
    entered = 0

    class Resource:
        async def __aenter__(self) -> str:
            nonlocal entered
            entered += 1
            return "entered"

        async def __aexit__(self, *args: object) -> None:
            del args

    unmanaged = Resource()
    managed = Resource()

    @module(
        providers=[
            ValueProvider("unmanaged", unmanaged),
            ValueProvider("managed", managed, manage=True),
        ]
    )
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)
    resolver = container.resolver(graph.root)
    assert await resolver.resolve("unmanaged") is unmanaged
    assert await resolver.resolve("managed") == "entered"
    assert entered == 1
    await container.close()


@pytest.mark.asyncio
async def test_cleanup_preserves_first_error_and_continues_lifo() -> None:
    exited: list[str] = []

    @asynccontextmanager
    async def first() -> AsyncIterator[str]:
        yield "first"
        exited.append("first")
        raise RuntimeError("first cleanup")

    @asynccontextmanager
    async def second() -> AsyncIterator[str]:
        yield "second"
        exited.append("second")
        raise RuntimeError("second cleanup")

    @module(
        providers=[FactoryProvider("first", first), FactoryProvider("second", second)]
    )
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)
    resolver = container.resolver(graph.root)
    await resolver.resolve("first")
    await resolver.resolve("second")
    error = await container.close()
    assert isinstance(error, RuntimeError)
    assert str(error) == "second cleanup"
    assert exited == ["second", "first"]


@pytest.mark.asyncio
async def test_synchronous_lifecycle_hooks_are_rejected() -> None:
    @module()
    class Root:
        def on_module_init(self) -> None:
            return None

    graph = await graph_for(Root)
    kernel = ApplicationKernel(graph)
    with pytest.raises(LifecycleError):
        await kernel.start()
    assert kernel.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_sync_resources_run_off_event_loop_thread() -> None:
    main_thread = threading.get_ident()
    threads: list[int] = []

    @contextmanager
    def resource() -> Iterator[str]:
        threads.append(threading.get_ident())
        yield "value"
        threads.append(threading.get_ident())

    @module(providers=[FactoryProvider("resource", resource)])
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)
    assert await container.resolver(graph.root).resolve("resource") == "value"
    await container.close()
    assert threads
    assert all(thread != main_thread for thread in threads)


@pytest.mark.asyncio
async def test_partial_provider_acquisition_rolls_back_nested_resources() -> None:
    closed = 0

    @asynccontextmanager
    async def dependency() -> AsyncIterator[object]:
        nonlocal closed
        yield object()
        closed += 1

    class Failing:
        def __init__(self, value: Annotated[object, Inject("dependency")]) -> None:
            del value
            raise RuntimeError("construction failed")

    @module(
        providers=[
            FactoryProvider("dependency", dependency),
            ClassProvider(Failing),
        ]
    )
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)
    with pytest.raises(RuntimeError, match="construction failed"):
        await container.resolver(graph.root).resolve(Failing)
    assert closed == 1
    await container.close()


class _RecordingBinder:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail
        self.bind_count = 0
        self.close_count = 0

    async def bind(self, kernel: ApplicationKernel) -> None:
        del kernel
        self.bind_count += 1
        self.events.append("bind")
        if self.fail:
            raise RuntimeError("bind failed")

    async def close(self) -> None:
        self.close_count += 1
        self.events.append("binder-close")


@pytest.mark.asyncio
async def test_kernel_startup_and_shutdown_hook_order() -> None:
    events: list[str] = []

    class Service:
        def __init__(self) -> None:
            events.append("service-construct")

        async def on_module_init(self) -> None:
            events.append("service-init")

        async def on_application_bootstrap(self) -> None:
            events.append("service-bootstrap")

        async def on_application_shutdown(self) -> None:
            events.append("service-shutdown")

        async def on_module_destroy(self) -> None:
            events.append("service-destroy")

    @module(providers=[ClassProvider(Service)])
    class Root:
        async def on_module_init(self) -> None:
            events.append("module-init")

        async def on_application_bootstrap(self) -> None:
            events.append("module-bootstrap")

        async def on_application_shutdown(self) -> None:
            events.append("module-shutdown")

        async def on_module_destroy(self) -> None:
            events.append("module-destroy")

    graph = await graph_for(Root)
    binder = _RecordingBinder(events)
    kernel = ApplicationKernel(graph, binder=binder)
    await kernel.start()
    assert kernel.state is ApplicationState.STARTED
    await kernel.shutdown()
    assert kernel.state is ApplicationState.STOPPED
    assert events == [
        "service-construct",
        "module-init",
        "service-init",
        "bind",
        "module-bootstrap",
        "service-bootstrap",
        "service-shutdown",
        "module-shutdown",
        "binder-close",
        "service-destroy",
        "module-destroy",
    ]
    assert binder.bind_count == 1
    assert binder.close_count == 1


@pytest.mark.asyncio
async def test_bind_failure_rolls_back_and_closes_binder_once() -> None:
    events: list[str] = []

    @module()
    class Root:
        async def on_module_init(self) -> None:
            events.append("init")

        async def on_module_destroy(self) -> None:
            events.append("destroy")

    graph = await graph_for(Root)
    binder = _RecordingBinder(events, fail=True)
    kernel = ApplicationKernel(graph, binder=binder)
    with pytest.raises(RuntimeError, match="bind failed"):
        await kernel.start()
    assert kernel.state is ApplicationState.FAILED
    assert binder.bind_count == 1
    assert binder.close_count == 1
    assert events == ["init", "bind", "binder-close", "destroy"]


@pytest.mark.asyncio
async def test_request_lease_closes_and_kernel_admission_is_bounded() -> None:
    class RequestValue:
        pass

    @module(providers=[ClassProvider(RequestValue, scope=Scope.REQUEST)])
    class Root:
        pass

    graph = await graph_for(Root)
    kernel = ApplicationKernel(
        graph,
        options=ApplicationOptions(
            shutdown_timeout=0.2,
            cancellation_grace=0.05,
            cleanup_reserve=0.05,
        ),
    )
    await kernel.start()
    scope = kernel.request_scope(graph.root)
    async with scope as resolver:
        assert await resolver.resolve(RequestValue)
    with pytest.raises(ScopeClosedError):
        await resolver.resolve(RequestValue)
    await kernel.shutdown()
    with pytest.raises(ApplicationStateError):
        await kernel.request_scope(graph.root).__aenter__()


@pytest.mark.asyncio
async def test_request_scope_waits_for_detached_resolver_use_before_cleanup() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def make_resource() -> str:
        started.set()
        await release.wait()
        return "value"

    @module(providers=[FactoryProvider("resource", make_resource, scope=Scope.REQUEST)])
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)
    scope = RequestScope(container, graph.root)
    resolver = await scope.__aenter__()
    task = asyncio.create_task(resolver.resolve("resource"))
    await started.wait()
    close_task = asyncio.create_task(scope.__aexit__(None, None, None))
    await asyncio.sleep(0)
    assert close_task.done() is False
    release.set()
    assert await task == "value"
    await close_task
    await container.close()


@pytest.mark.asyncio
async def test_shutdown_bounds_hanging_hooks_and_reaches_stopped_state() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    @module()
    class Root:
        async def on_application_shutdown(self) -> None:
            started.set()
            await release.wait()

    graph = await graph_for(Root)
    kernel = ApplicationKernel(
        graph,
        options=ApplicationOptions(
            shutdown_timeout=0.05,
            cancellation_grace=0,
            cleanup_reserve=0,
        ),
    )
    await kernel.start()
    with pytest.raises(TimeoutError):
        await kernel.shutdown()
    assert started.is_set()
    assert kernel.state is ApplicationState.STOPPED
    release.set()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_cancelled_shutdown_still_finalizes_state() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    @module()
    class Root:
        async def on_application_shutdown(self) -> None:
            started.set()
            await release.wait()

    graph = await graph_for(Root)
    binder = _RecordingBinder([])
    kernel = ApplicationKernel(
        graph,
        binder=binder,
        options=ApplicationOptions(
            shutdown_timeout=1,
            cancellation_grace=0,
            cleanup_reserve=0,
        ),
    )
    await kernel.start()
    shutdown_task = asyncio.create_task(kernel.shutdown())
    await started.wait()
    shutdown_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await shutdown_task
    assert kernel.state is ApplicationState.STOPPED
    assert binder.close_count == 1
    release.set()
    await asyncio.sleep(0)
