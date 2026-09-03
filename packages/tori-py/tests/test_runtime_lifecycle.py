import asyncio
import contextvars
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Annotated, cast

import pytest
import tori_py.core.runtime as runtime_module
from tori_py import (
    AliasProvider,
    ApplicationOptions,
    ApplicationStateError,
    ClassProvider,
    DeferredModule,
    FactoryProvider,
    Inject,
    LifecycleError,
    ModuleSpec,
    Scope,
    ScopeClosedError,
    ScopeError,
    ValueProvider,
    WorkScopeFactory,
    compile_graph,
    module,
)
from tori_py.core.runtime import (
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
async def test_resolve_ref_requires_the_exact_ref_to_be_visible() -> None:
    @module(
        providers=[
            ValueProvider("private", "private-value"),
            ValueProvider("public", "public-value"),
        ],
        exports=["public"],
    )
    class Feature:
        pass

    @module(imports=[Feature])
    class Root:
        pass

    graph = await graph_for(Root)
    feature_id = next(
        module_plan.module_id
        for module_plan in graph.modules
        if module_plan.module is Feature
    )
    private_ref = next(
        ref
        for ref in graph.providers
        if ref.module_id == feature_id and ref.token == "private"
    )
    public_ref = graph.visibility[(graph.root, "public")]
    container = Container(graph)

    assert (
        await container.resolver(graph.root).resolve_ref(public_ref) == "public-value"
    )
    assert (
        await container.resolver(feature_id).resolve_ref(private_ref) == "private-value"
    )
    with pytest.raises(ScopeError, match="not visible"):
        await container.resolver(graph.root).resolve_ref(private_ref)

    await container.close()


@pytest.mark.asyncio
async def test_empty_request_scope_closes_without_a_cleanup_task() -> None:
    @module(providers=[ValueProvider("singleton", "value")])
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)
    scope = RequestScope(container, graph.root)

    async with scope as resolver:
        assert await resolver.resolve("singleton") == "value"

    assert scope._cleanup_task is None
    await container.close()


@pytest.mark.asyncio
async def test_live_request_resolver_rejects_cross_task_use() -> None:
    created = 0

    async def make_value() -> object:
        nonlocal created
        created += 1
        return object()

    @module(providers=[FactoryProvider("request", make_value, scope=Scope.REQUEST)])
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)
    async with RequestScope(container, graph.root) as resolver:
        task = asyncio.create_task(resolver.resolve("request"))
        with pytest.raises(ScopeError, match="owner task"):
            await task

    assert created == 0
    await container.close()


@pytest.mark.asyncio
async def test_request_scope_resolve_ref_rejects_cross_task_use() -> None:
    @module(providers=[ValueProvider("value", object())])
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)
    ref = graph.visibility[(graph.root, "value")]
    scope = RequestScope(container, graph.root)
    async with scope:
        task = asyncio.create_task(scope.resolve_ref(ref))
        with pytest.raises(ScopeError, match="owner task"):
            await task

    await container.close()


@pytest.mark.asyncio
async def test_application_resolver_shares_eager_singletons_across_tasks() -> None:
    value = object()

    @module(providers=[ValueProvider("singleton", value)])
    class Root:
        pass

    graph = await graph_for(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()
    resolver = kernel.resolver(graph.root)

    first, second = await asyncio.gather(
        asyncio.create_task(resolver.resolve("singleton")),
        asyncio.create_task(resolver.resolve("singleton")),
    )

    assert first is value
    assert second is value
    await kernel.shutdown()


@pytest.mark.asyncio
async def test_concurrent_request_tasks_own_separate_scopes() -> None:
    async def make_value() -> object:
        await asyncio.sleep(0)
        return object()

    @module(providers=[FactoryProvider("request", make_value, scope=Scope.REQUEST)])
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)

    async def resolve_in_scope() -> object:
        async with RequestScope(container, graph.root) as resolver:
            value = await resolver.resolve("request")
            assert await resolver.resolve("request") is value
            return value

    first, second = await asyncio.gather(
        asyncio.create_task(resolve_in_scope()),
        asyncio.create_task(resolve_in_scope()),
    )

    assert first is not second
    await container.close()


@pytest.mark.asyncio
async def test_declared_async_factory_does_not_check_awaitability_at_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def make_value() -> str:
        return "value"

    @module(providers=[FactoryProvider("value", make_value)])
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)

    def fail_awaitable_check(value: object) -> bool:
        raise AssertionError(f"unexpected awaitability check for {value!r}")

    monkeypatch.setattr(runtime_module.inspect, "isawaitable", fail_awaitable_check)
    assert await container.resolver(graph.root).resolve("value") == "value"
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
        try:
            yield object()
        finally:
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
async def test_request_scope_rejects_detached_use_of_a_cached_resource() -> None:
    closed = asyncio.Event()

    @asynccontextmanager
    async def resource() -> AsyncIterator[str]:
        try:
            yield "value"
        finally:
            closed.set()

    @module(providers=[FactoryProvider("resource", resource, scope=Scope.REQUEST)])
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)
    async with RequestScope(container, graph.root) as resolver:
        assert await resolver.resolve("resource") == "value"
        detached = asyncio.create_task(resolver.resolve("resource"))
        with pytest.raises(ScopeError, match="owner task"):
            await detached

    assert closed.is_set()
    await container.close()


@pytest.mark.asyncio
async def test_work_scope_factory_uses_module_identity_and_scoped_providers() -> None:
    request_instances: list[object] = []
    transient_instances: list[object] = []

    class RequestValue:
        def __init__(self) -> None:
            request_instances.append(self)

    class TransientValue:
        def __init__(self) -> None:
            transient_instances.append(self)

    class Consumer:
        def __init__(self, scopes: WorkScopeFactory) -> None:
            self.scopes = scopes

    @module(
        providers=[
            ClassProvider(Consumer),
            ClassProvider(RequestValue, scope=Scope.REQUEST),
            ClassProvider(TransientValue, scope=Scope.TRANSIENT),
        ]
    )
    class Root:
        pass

    graph = await graph_for(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()
    consumer = await kernel.resolver(graph.root).resolve(Consumer)
    assert isinstance(consumer, Consumer)
    assert consumer.scopes.module_id == graph.root

    async with consumer.scopes.open() as first:
        request_value = await first.resolve(RequestValue)
        assert await first.resolve(RequestValue) is request_value
        assert await first.resolve(TransientValue) is not await first.resolve(
            TransientValue
        )
    async with consumer.scopes.open() as second:
        assert await second.resolve(RequestValue) is not request_value

    assert len(request_instances) == 2
    assert len(transient_instances) == 2

    inherited: contextvars.ContextVar[str | None] = contextvars.ContextVar(
        "inherited",
        default=None,
    )
    token = inherited.set("request-context")
    try:

        async def detached_operation(resolver) -> object:
            assert inherited.get() is None
            return await resolver.resolve(RequestValue)

        detached_value = await consumer.scopes.run(detached_operation)
    finally:
        inherited.reset(token)
    assert isinstance(detached_value, RequestValue)

    await kernel.shutdown()
    with pytest.raises(ApplicationStateError, match="work scopes"):
        await consumer.scopes.open().__aenter__()


@pytest.mark.asyncio
async def test_work_scope_resolver_rejects_child_task_use() -> None:
    created = 0

    class RequestValue:
        def __init__(self) -> None:
            nonlocal created
            created += 1

    class Consumer:
        def __init__(self, scopes: WorkScopeFactory) -> None:
            self.scopes = scopes

    @module(
        providers=[
            ClassProvider(Consumer),
            ClassProvider(RequestValue, scope=Scope.REQUEST),
        ]
    )
    class Root:
        pass

    graph = await graph_for(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()
    consumer = cast(Consumer, await kernel.resolver(graph.root).resolve(Consumer))

    async def operation(resolver) -> None:
        task = asyncio.create_task(resolver.resolve(RequestValue))
        with pytest.raises(ScopeError, match="owner task"):
            await task

    await consumer.scopes.run(operation)

    assert created == 0
    await kernel.shutdown()


@pytest.mark.asyncio
async def test_work_scope_factory_preserves_keyed_dynamic_module_identity() -> None:
    class Consumer:
        def __init__(self, scopes: WorkScopeFactory) -> None:
            self.scopes = scopes

    class DynamicModule:
        pass

    def descriptor(key: str) -> DeferredModule:
        return DeferredModule(
            DynamicModule,
            key,
            lambda: ModuleSpec(
                providers=[ClassProvider(Consumer)],
            ),
        )

    first = descriptor("first")
    second = descriptor("second")

    @module(imports=[first, second])
    class Root:
        pass

    graph = await graph_for(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()
    dynamic_ids = [
        plan.module_id for plan in graph.modules if plan.module is DynamicModule
    ]
    consumers = [
        cast(Consumer, await kernel.resolver(module_id).resolve(Consumer))
        for module_id in dynamic_ids
    ]
    assert [consumer.scopes.module_id.key for consumer in consumers] == [
        "first",
        "second",
    ]
    assert consumers[0].scopes is not consumers[1].scopes
    await kernel.shutdown()


@pytest.mark.asyncio
async def test_quiescence_keeps_work_open_after_request_admission_closes() -> None:
    events: list[str] = []
    quiescing = asyncio.Event()
    release = asyncio.Event()

    class Coordinator:
        def __init__(self, scopes: WorkScopeFactory) -> None:
            self.scopes = scopes

        async def on_application_bootstrap(self) -> None:
            async with self.scopes.open():
                events.append("bootstrap-work")

        async def on_application_quiesce(self, context) -> None:
            assert context.remaining() is None or context.remaining() >= 0
            events.append("quiesce")
            quiescing.set()
            await release.wait()

        async def on_application_shutdown(self) -> None:
            events.append("shutdown")

        async def on_module_destroy(self) -> None:
            events.append("destroy")

    @module(providers=[ClassProvider(Coordinator)])
    class Root:
        pass

    graph = await graph_for(Root)
    binder = _RecordingBinder(events)
    kernel = ApplicationKernel(graph, binder=binder)
    await kernel.start()
    coordinator = await kernel.resolver(graph.root).resolve(Coordinator)
    assert isinstance(coordinator, Coordinator)

    shutdown = asyncio.create_task(kernel.shutdown())
    await quiescing.wait()
    with pytest.raises(ApplicationStateError, match="request scopes"):
        await kernel.request_scope(graph.root).__aenter__()
    async with coordinator.scopes.open():
        events.append("quiesce-work")
    release.set()
    await shutdown

    assert events == [
        "bind",
        "bootstrap-work",
        "quiesce",
        "quiesce-work",
        "shutdown",
        "binder-close",
        "destroy",
    ]


@pytest.mark.asyncio
async def test_cancelled_scope_waiter_does_not_cancel_cleanup() -> None:
    cleanup_started = asyncio.Event()
    cleanup_finished = asyncio.Event()
    release_cleanup = asyncio.Event()
    cleanup_count = 0

    @asynccontextmanager
    async def resource() -> AsyncIterator[str]:
        nonlocal cleanup_count
        try:
            yield "resource"
        finally:
            cleanup_started.set()
            await release_cleanup.wait()
            cleanup_count += 1

    @module(providers=[FactoryProvider("resource", resource, scope=Scope.REQUEST)])
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)
    resolver = None

    async def use_scope() -> None:
        nonlocal resolver
        scope = RequestScope(
            container,
            graph.root,
            on_close=lambda _: cleanup_finished.set(),
        )
        async with scope as resolver:
            assert await resolver.resolve("resource") == "resource"

    owner = asyncio.create_task(use_scope())
    await cleanup_started.wait()
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    release_cleanup.set()
    await cleanup_finished.wait()
    assert cleanup_count == 1
    assert resolver is not None
    with pytest.raises(ScopeClosedError):
        await resolver.resolve("resource")
    await container.close()


@pytest.mark.asyncio
async def test_cancelled_owner_resolution_rolls_back_and_allows_retry() -> None:
    construction_started = asyncio.Event()
    construction_cancelled = asyncio.Event()
    attempts = 0
    closed = 0

    @asynccontextmanager
    async def resource() -> AsyncIterator[str]:
        nonlocal attempts, closed
        attempts += 1
        if attempts == 1:
            construction_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                construction_cancelled.set()
                raise
        try:
            yield "resource"
        finally:
            closed += 1

    @module(providers=[FactoryProvider("resource", resource, scope=Scope.REQUEST)])
    class Root:
        pass

    graph = await graph_for(Root)
    container = Container(graph)
    scope = RequestScope(container, graph.root)
    resolver = await scope.__aenter__()
    try:
        owner = asyncio.current_task()
        assert owner is not None
        asyncio.get_running_loop().call_soon(owner.cancel)
        with pytest.raises(asyncio.CancelledError):
            await resolver.resolve("resource")
        owner.uncancel()

        assert construction_started.is_set()
        assert construction_cancelled.is_set()
        assert await resolver.resolve("resource") == "resource"
    finally:
        await scope.__aexit__(None, None, None)
        await container.close()

    assert attempts == 2
    assert closed == 1


@pytest.mark.asyncio
async def test_timed_out_quiesce_is_cancelled_before_teardown() -> None:
    events: list[str] = []

    class Coordinator:
        async def on_application_quiesce(self, context) -> None:
            del context
            events.append("quiesce-start")
            try:
                await asyncio.Event().wait()
            finally:
                events.append("quiesce-cancel")

        async def on_application_shutdown(self) -> None:
            events.append("shutdown")

        async def on_module_destroy(self) -> None:
            events.append("destroy")

    @module(providers=[ClassProvider(Coordinator)])
    class Root:
        pass

    graph = await graph_for(Root)
    binder = _RecordingBinder(events)
    kernel = ApplicationKernel(
        graph,
        binder=binder,
        options=ApplicationOptions(
            shutdown_timeout=0.05,
            cancellation_grace=0,
            cleanup_reserve=0,
        ),
    )
    await kernel.start()
    with pytest.raises(TimeoutError):
        await kernel.shutdown()
    assert events == [
        "bind",
        "quiesce-start",
        "quiesce-cancel",
        "shutdown",
        "binder-close",
        "destroy",
    ]


@pytest.mark.asyncio
async def test_cancelled_startup_joins_singleton_construction_before_rollback() -> None:
    construction_started = asyncio.Event()
    construction_cancelled = asyncio.Event()

    async def singleton() -> object:
        construction_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            construction_cancelled.set()
        return object()

    @module(providers=[FactoryProvider("singleton", singleton)])
    class Root:
        pass

    graph = await graph_for(Root)
    kernel = ApplicationKernel(graph)
    startup = asyncio.create_task(kernel.start())
    await construction_started.wait()
    startup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await startup
    assert construction_cancelled.is_set()
    assert kernel.state is ApplicationState.FAILED


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
    assert kernel.state is ApplicationState.STOPPING
    release.set()
    await kernel.shutdown()
    assert kernel.state is ApplicationState.STOPPED
    assert binder.close_count == 1
