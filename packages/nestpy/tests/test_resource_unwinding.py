import asyncio
import logging
from collections.abc import Callable
from types import TracebackType
from typing import Annotated

import pytest
from nestpy import (
    ClassProvider,
    FactoryProvider,
    Inject,
    ResourceError,
    Scope,
    ScopeCancellationError,
    ScopeFinalizationError,
    WorkScopeFactory,
    compile_graph,
    module,
)
from nestpy.core.runtime import (
    ApplicationKernel,
    Container,
    RequestScope,
    _scope_cleanup_error,
)

type ExitTuple = tuple[
    type[BaseException] | None,
    BaseException | None,
    TracebackType | None,
]


class AsyncResource:
    def __init__(
        self,
        name: str,
        exits: list[tuple[str, ExitTuple]],
        *,
        error: BaseException | None = None,
        result: object = None,
    ) -> None:
        self.name = name
        self.exits = exits
        self.error = error
        self.result = result

    async def __aenter__(self) -> str:
        return self.name

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> object:
        self.exits.append((self.name, (exc_type, exc, tb)))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_clean_scope_collects_all_cleanup_failures_in_lifo_order() -> None:
    exits: list[tuple[str, ExitTuple]] = []
    first_error = RuntimeError("first cleanup")
    second_error = ValueError("second cleanup")

    @module(
        providers=[
            FactoryProvider(
                "first",
                lambda: AsyncResource("first", exits, error=first_error),
                scope=Scope.REQUEST,
            ),
            FactoryProvider(
                "second",
                lambda: AsyncResource("second", exits, error=second_error),
                scope=Scope.REQUEST,
            ),
        ]
    )
    class Root:
        pass

    graph = await compile_graph(Root)
    container = Container(graph)

    with pytest.raises(ScopeFinalizationError) as captured:
        async with RequestScope(container, graph.root) as resolver:
            await resolver.resolve("first")
            await resolver.resolve("second")

    assert captured.value.body_error is None
    assert captured.value.cleanup_errors == (second_error, first_error)
    assert [name for name, _ in exits] == ["second", "first"]
    assert all(exc_info == (None, None, None) for _, exc_info in exits)
    await container.close()


@pytest.mark.asyncio
async def test_body_failure_is_supplied_unchanged_to_every_exit() -> None:
    exits: list[tuple[str, ExitTuple]] = []
    outer_error = RuntimeError("outer cleanup")
    inner_error = ValueError("inner cleanup")
    body_error = LookupError("body failed")

    @module(
        providers=[
            FactoryProvider(
                "outer",
                lambda: AsyncResource("outer", exits, error=outer_error),
                scope=Scope.REQUEST,
            ),
            FactoryProvider(
                "inner",
                lambda: AsyncResource("inner", exits, error=inner_error),
                scope=Scope.REQUEST,
            ),
        ]
    )
    class Root:
        pass

    graph = await compile_graph(Root)
    container = Container(graph)

    with pytest.raises(ScopeFinalizationError) as captured:
        async with RequestScope(container, graph.root) as resolver:
            await resolver.resolve("outer")
            await resolver.resolve("inner")
            raise body_error

    assert captured.value.body_error is body_error
    assert captured.value.cleanup_errors == (inner_error, outer_error)
    assert [name for name, _ in exits] == ["inner", "outer"]
    assert all(exc_info[0] is LookupError for _, exc_info in exits)
    assert all(exc_info[1] is body_error for _, exc_info in exits)
    assert exits[0][1][2] is exits[1][1][2]
    await container.close()


@pytest.mark.asyncio
async def test_body_failure_passes_through_unchanged_after_clean_exit() -> None:
    exits: list[tuple[str, ExitTuple]] = []
    body_error = RuntimeError("body failed")

    @module(
        providers=[
            FactoryProvider(
                "resource",
                lambda: AsyncResource("resource", exits),
                scope=Scope.REQUEST,
            )
        ]
    )
    class Root:
        pass

    graph = await compile_graph(Root)
    container = Container(graph)

    with pytest.raises(RuntimeError) as captured:
        async with RequestScope(container, graph.root) as resolver:
            await resolver.resolve("resource")
            raise body_error

    assert captured.value is body_error
    assert exits[0][1][1] is body_error
    await container.close()


@pytest.mark.asyncio
async def test_truthy_exit_is_an_ordered_cleanup_failure_and_cannot_suppress() -> None:
    exits: list[tuple[str, ExitTuple]] = []
    outer_error = RuntimeError("outer cleanup")
    body_error = ValueError("body failed")

    @module(
        providers=[
            FactoryProvider(
                "outer",
                lambda: AsyncResource("outer", exits, error=outer_error),
                scope=Scope.REQUEST,
            ),
            FactoryProvider(
                "suppressor",
                lambda: AsyncResource("suppressor", exits, result=True),
                scope=Scope.REQUEST,
            ),
        ]
    )
    class Root:
        pass

    graph = await compile_graph(Root)
    container = Container(graph)

    with pytest.raises(ScopeFinalizationError) as captured:
        async with RequestScope(container, graph.root) as resolver:
            await resolver.resolve("outer")
            await resolver.resolve("suppressor")
            raise body_error

    suppression_error, cleanup_error = captured.value.cleanup_errors
    assert captured.value.body_error is body_error
    assert isinstance(suppression_error, ResourceError)
    assert suppression_error.diagnostic_code == "resource.cleanup_error"
    assert cleanup_error is outer_error
    assert [name for name, _ in exits] == ["suppressor", "outer"]
    assert all(exc_info[1] is body_error for _, exc_info in exits)
    await container.close()


@pytest.mark.asyncio
async def test_cancellation_with_cleanup_errors_remains_cancellation() -> None:
    exits: list[tuple[str, ExitTuple]] = []
    cleanup_error = RuntimeError("cleanup failed")
    cancellation = asyncio.CancelledError("stop")

    @module(
        providers=[
            FactoryProvider(
                "resource",
                lambda: AsyncResource("resource", exits, error=cleanup_error),
                scope=Scope.REQUEST,
            )
        ]
    )
    class Root:
        pass

    graph = await compile_graph(Root)
    container = Container(graph)

    with pytest.raises(ScopeCancellationError) as captured:
        async with RequestScope(container, graph.root) as resolver:
            await resolver.resolve("resource")
            raise cancellation

    assert isinstance(captured.value, asyncio.CancelledError)
    assert captured.value.cancellation is cancellation
    assert captured.value.body_error is cancellation
    assert captured.value.cleanup_errors == (cleanup_error,)
    assert exits[0][1][1] is cancellation
    await container.close()


@pytest.mark.asyncio
async def test_cleanup_originated_cancellation_remains_cancellation() -> None:
    exits: list[tuple[str, ExitTuple]] = []
    cancellation = asyncio.CancelledError("cleanup cancelled")

    @module(
        providers=[
            FactoryProvider(
                "resource",
                lambda: AsyncResource("resource", exits, error=cancellation),
                scope=Scope.REQUEST,
            )
        ]
    )
    class Root:
        pass

    graph = await compile_graph(Root)
    container = Container(graph)
    with pytest.raises(ScopeCancellationError) as captured:
        async with RequestScope(container, graph.root) as resolver:
            await resolver.resolve("resource")

    assert captured.value.cancellation is cancellation
    assert captured.value.cleanup_errors == ()
    await container.close()


@pytest.mark.parametrize("signal_factory", [KeyboardInterrupt, SystemExit])
def test_cleanup_originated_process_control_keeps_identity(
    signal_factory: Callable[[], KeyboardInterrupt | SystemExit],
) -> None:
    signal = signal_factory()
    result = _scope_cleanup_error(None, (signal, RuntimeError("secondary")))
    assert result is signal
    assert signal.__notes__ == ["Nestpy scope cleanup failed: RuntimeError: secondary"]


@pytest.mark.asyncio
async def test_cancelled_work_scope_reports_cleanup_without_losing_cancellation() -> (
    None
):
    exits: list[tuple[str, ExitTuple]] = []
    cleanup_error = RuntimeError("cleanup failed")
    operation_started = asyncio.Event()

    class Consumer:
        def __init__(self, scopes: WorkScopeFactory) -> None:
            self.scopes = scopes

    @module(
        providers=[
            ClassProvider(Consumer),
            FactoryProvider(
                "resource",
                lambda: AsyncResource("resource", exits, error=cleanup_error),
                scope=Scope.REQUEST,
            ),
        ]
    )
    class Root:
        pass

    graph = await compile_graph(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()
    consumer = await kernel.resolver(graph.root).resolve(Consumer)
    assert isinstance(consumer, Consumer)

    async def operation(resolver) -> None:
        await resolver.resolve("resource")
        operation_started.set()
        await asyncio.Event().wait()

    invocation = asyncio.create_task(consumer.scopes.run(operation))
    await operation_started.wait()
    invocation.cancel()

    with pytest.raises(ScopeCancellationError) as captured:
        await invocation

    assert isinstance(captured.value, asyncio.CancelledError)
    assert isinstance(captured.value.cancellation, asyncio.CancelledError)
    assert captured.value.cleanup_errors == (cleanup_error,)
    assert exits[0][1][1] is captured.value.cancellation
    await kernel.shutdown()


@pytest.mark.parametrize("signal_factory", [KeyboardInterrupt, SystemExit])
@pytest.mark.asyncio
async def test_process_control_failure_keeps_identity_and_observes_cleanup(
    signal_factory: Callable[[], KeyboardInterrupt | SystemExit],
    caplog: pytest.LogCaptureFixture,
) -> None:
    exits: list[tuple[str, ExitTuple]] = []
    cleanup_error = RuntimeError("cleanup failed")

    @module(
        providers=[
            FactoryProvider(
                "resource",
                lambda: AsyncResource("resource", exits, error=cleanup_error),
                scope=Scope.REQUEST,
            )
        ]
    )
    class Root:
        pass

    graph = await compile_graph(Root)
    container = Container(graph)
    scope = RequestScope(container, graph.root)
    resolver = await scope.__aenter__()
    await resolver.resolve("resource")
    signal = signal_factory()

    with caplog.at_level(logging.ERROR, logger="nestpy.core.runtime"):
        result = await scope.__aexit__(type(signal), signal, None)

    assert result is None
    assert exits[0][1][1] is signal
    assert signal.__notes__ == [
        "Nestpy scope cleanup failed: RuntimeError: cleanup failed"
    ]
    assert "Resource cleanup failed" in caplog.messages
    await container.close()


@pytest.mark.asyncio
async def test_partial_acquisition_rollback_preserves_body_and_cleanup_errors() -> None:
    exits: list[tuple[str, ExitTuple]] = []
    cleanup_error = RuntimeError("dependency cleanup failed")
    construction_error = ValueError("construction failed")

    def fail(value: Annotated[str, Inject("dependency")]) -> object:
        del value
        raise construction_error

    @module(
        providers=[
            FactoryProvider(
                "dependency",
                lambda: AsyncResource(
                    "dependency",
                    exits,
                    error=cleanup_error,
                ),
                scope=Scope.REQUEST,
            ),
            FactoryProvider("consumer", fail, scope=Scope.REQUEST),
        ]
    )
    class Root:
        pass

    graph = await compile_graph(Root)
    container = Container(graph)

    with pytest.raises(ScopeFinalizationError) as captured:
        async with RequestScope(container, graph.root) as resolver:
            await resolver.resolve("consumer")

    assert captured.value.body_error is construction_error
    assert captured.value.cleanup_errors == (cleanup_error,)
    assert exits[0][1][1] is construction_error
    await container.close()


@pytest.mark.asyncio
async def test_sync_exit_receives_body_and_truthy_result_is_rejected() -> None:
    exits: list[ExitTuple] = []
    body_error = RuntimeError("body failed")

    class SyncResource:
        def __enter__(self) -> str:
            return "resource"

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> bool:
            exits.append((exc_type, exc, tb))
            return True

    @module(providers=[FactoryProvider("resource", SyncResource, scope=Scope.REQUEST)])
    class Root:
        pass

    graph = await compile_graph(Root)
    container = Container(graph)

    with pytest.raises(ScopeFinalizationError) as captured:
        async with RequestScope(container, graph.root) as resolver:
            await resolver.resolve("resource")
            raise body_error

    assert captured.value.body_error is body_error
    assert len(captured.value.cleanup_errors) == 1
    assert isinstance(captured.value.cleanup_errors[0], ResourceError)
    assert exits[0][1] is body_error
    await container.close()


@pytest.mark.asyncio
async def test_work_scope_exposes_application_id_and_aggregates_cleanup() -> None:
    exits: list[tuple[str, ExitTuple]] = []
    cleanup_error = RuntimeError("work cleanup failed")
    body_error = ValueError("work failed")

    class Consumer:
        def __init__(self, scopes: WorkScopeFactory) -> None:
            self.scopes = scopes

    @module(
        providers=[
            ClassProvider(Consumer),
            FactoryProvider(
                "resource",
                lambda: AsyncResource("resource", exits, error=cleanup_error),
                scope=Scope.REQUEST,
            ),
        ]
    )
    class Root:
        pass

    graph = await compile_graph(Root)
    kernel = ApplicationKernel(graph)
    await kernel.start()
    consumer = await kernel.resolver(graph.root).resolve(Consumer)
    assert isinstance(consumer, Consumer)
    assert consumer.scopes.application_id == Root.__qualname__

    async def operation(resolver) -> None:
        await resolver.resolve("resource")
        raise body_error

    with pytest.raises(ScopeFinalizationError) as captured:
        await consumer.scopes.run(operation)

    assert captured.value.body_error is body_error
    assert captured.value.cleanup_errors == (cleanup_error,)
    assert exits[0][1][1] is body_error
    await kernel.shutdown()
