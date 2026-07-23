import asyncio
import contextvars
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

import pytest
from cqrs_core import Command, CommandBus, CommandHandler, HandlerKind
from nestpy import (
    ClassProvider,
    DeferredModule,
    ExecutionContext,
    FactoryProvider,
    ModuleId,
    ModuleSpec,
    ProviderRef,
    Scope,
    ScopeCancellationError,
    ScopeFinalizationError,
    module,
)
from nestpy.testing import TestingModule
from nestpy_cqrs import (
    CqrsConfigurationError,
    CqrsHandlerExitError,
    CqrsInterceptorBinding,
    CqrsInterceptorPhase,
    CqrsInvocationCompletion,
    CqrsInvocationContext,
    CqrsInvocationInterceptor,
    CqrsModule,
    CqrsModuleOptions,
    CqrsPipelineStateError,
    CqrsScopeCompletion,
    use_cqrs_interceptors,
)
from nestpy_cqrs import (
    bind_command_handler as command_handler,
)


@dataclass(frozen=True, slots=True)
class Invoke(Command[int]):
    value: int


class RecordingInterceptor:
    def __init__(
        self,
        name: str,
        calls: list[str],
        contexts: list[CqrsInvocationContext] | None = None,
    ) -> None:
        self.name = name
        self.calls = calls
        self.contexts = contexts

    async def intercept(
        self,
        context: CqrsInvocationContext,
        next: Callable[[], Awaitable[object]],
    ) -> object:
        self.calls.append(f"{self.name}:before")
        if self.name == "handler":
            context.on_handler_exit(lambda: self.calls.append("terminal:exit"))
        if self.contexts is not None:
            self.contexts.append(context)
        result = await next()
        self.calls.append(f"{self.name}:after")
        return result


def test_public_declarations_validate_and_compose_metadata() -> None:
    interceptor = RecordingInterceptor("direct", [])
    binding = CqrsInterceptorBinding(interceptor, cast(Any, "outer"))
    assert binding.phase is CqrsInterceptorPhase.OUTER
    assert isinstance(interceptor, CqrsInvocationInterceptor)
    assert CqrsInvocationCompletion()

    with pytest.raises(CqrsConfigurationError, match="phase"):
        CqrsInterceptorBinding(interceptor, cast(Any, "unknown"))
    with pytest.raises(CqrsConfigurationError, match="intercept"):
        CqrsInterceptorBinding(cast(Any, object()), CqrsInterceptorPhase.HANDLER)
    with pytest.raises(CqrsConfigurationError, match="graph-phase"):
        CqrsModuleOptions(command_interceptors=(binding,))

    decorator = use_cqrs_interceptors(interceptor)

    @decorator
    class Handler:
        pass

    decorator(Handler)

    with pytest.raises(CqrsConfigurationError, match="handler_kinds"):
        CqrsInterceptorBinding(
            interceptor,
            CqrsInterceptorPhase.OUTER,
            handler_kinds=cast(Any, ("command",)),
        )


@pytest.mark.asyncio
async def test_phase_order_context_mapping_and_reverse_unwind() -> None:
    calls: list[str] = []
    contexts: list[CqrsInvocationContext] = []
    outer = RecordingInterceptor("outer", calls, contexts)
    graph = RecordingInterceptor("graph", calls)
    handler_interceptor = RecordingInterceptor("handler", calls)
    ambient: contextvars.ContextVar[str | None] = contextvars.ContextVar(
        "cqrs_invocation_ambient", default=None
    )

    @CommandHandler(Invoke)
    @use_cqrs_interceptors(handler_interceptor)
    class Handler:
        async def handle(self, command: Invoke) -> int:
            calls.append("terminal")
            assert ambient.get() is None
            return command.value

    @module(providers=[ClassProvider(Handler)], exports=[Handler])
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[
            command_handler(
                Invoke,
                Handler,
                interceptors=[
                    CqrsInterceptorBinding(outer, CqrsInterceptorPhase.OUTER)
                ],
            )
        ],
        options=CqrsModuleOptions(command_interceptors=(graph,)),
        key="context",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "context"))
    assert isinstance(commands, CommandBus)
    token = ambient.set("http")
    try:
        assert await commands.execute(Invoke(9)) == 9
    finally:
        ambient.reset(token)

    assert calls == [
        "outer:before",
        "graph:before",
        "handler:before",
        "terminal",
        "terminal:exit",
        "handler:after",
        "graph:after",
        "outer:after",
    ]
    context = contexts[0]
    assert isinstance(context, ExecutionContext)
    assert context.application_id == Root.__qualname__
    assert context.module_id == Feature.__qualname__
    assert context.route_id is None
    assert context.request_id is None
    assert context.execution_kind == "cqrs"
    assert context.handler_kind is HandlerKind.COMMAND
    assert context.owner_module == ModuleId(Feature)
    assert context.handler_ref == ProviderRef(ModuleId(Feature), Handler)
    assert context.message == Invoke(9)
    assert context.envelope is context.dispatch_context.envelope
    assert isinstance(context.metadata, MappingProxyType)
    assert context.metadata["handler_kind"] == "command"
    with pytest.raises(TypeError):
        context.metadata["changed"] = True  # type: ignore[index]
    await application.close()


@pytest.mark.asyncio
async def test_next_is_one_shot_and_handler_runs_once() -> None:
    calls = 0

    class Twice:
        async def intercept(
            self,
            context: CqrsInvocationContext,
            next: Callable[[], Awaitable[object]],
        ) -> object:
            del context
            await next()
            return await next()

    class Handler:
        async def handle(self, command: Invoke) -> int:
            nonlocal calls
            calls += 1
            return command.value

    @module(providers=[ClassProvider(Handler)], exports=[Handler])
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[command_handler(Invoke, Handler)],
        options=CqrsModuleOptions(command_interceptors=(Twice(),)),
        key="one-shot",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "one-shot"))
    assert isinstance(commands, CommandBus)
    with pytest.raises(CqrsPipelineStateError, match="called twice"):
        await commands.execute(Invoke(1))
    assert calls == 1
    await application.close()


@pytest.mark.asyncio
async def test_handler_exit_callbacks_preserve_primary_and_attempt_all() -> None:
    body_error = RuntimeError("handler failed")
    first = ValueError("first callback")
    second = LookupError("second callback")
    calls: list[str] = []

    class TerminalCallbacks:
        async def intercept(self, context, next):
            def fail_first() -> None:
                calls.append("first")
                raise first

            def fail_second() -> None:
                calls.append("second")
                raise second

            context.on_handler_exit(fail_first)
            context.on_handler_exit(fail_second)
            return await next()

    class Handler:
        async def handle(self, command: Invoke) -> int:
            del command
            raise body_error

    @module(providers=[ClassProvider(Handler)], exports=[Handler])
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[command_handler(Invoke, Handler)],
        options=CqrsModuleOptions(command_interceptors=(TerminalCallbacks(),)),
        key="terminal-callbacks",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(
        CommandBus,
        module=(CqrsModule, "terminal-callbacks"),
    )
    assert isinstance(commands, CommandBus)
    with pytest.raises(CqrsHandlerExitError) as captured:
        await commands.execute(Invoke(1))
    assert captured.value.body_error is body_error
    assert captured.value.callback_errors == (second, first)
    assert captured.value.__cause__ is body_error
    assert calls == ["second", "first"]
    await application.close()


@pytest.mark.asyncio
async def test_short_circuit_keeps_later_providers_and_handler_lazy() -> None:
    constructions: list[str] = []

    class Stop:
        async def intercept(
            self,
            context: CqrsInvocationContext,
            next: Callable[[], Awaitable[object]],
        ) -> object:
            del context, next
            return 42

    class Later:
        def __init__(self) -> None:
            constructions.append("interceptor")

        async def intercept(
            self,
            context: CqrsInvocationContext,
            next: Callable[[], Awaitable[object]],
        ) -> object:
            del context
            return await next()

    class Handler:
        def __init__(self) -> None:
            constructions.append("handler")

        async def handle(self, command: Invoke) -> int:
            return command.value

    @module(
        providers=[
            ClassProvider(Later, scope=Scope.REQUEST),
            ClassProvider(Handler, scope=Scope.REQUEST),
        ],
        exports=[Handler],
    )
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[command_handler(Invoke, Handler)],
        options=CqrsModuleOptions(command_interceptors=(Stop(), Later)),
        key="lazy",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "lazy"))
    assert isinstance(commands, CommandBus)
    assert await commands.execute(Invoke(1)) == 42
    assert constructions == []
    await application.close()


@pytest.mark.asyncio
async def test_tokens_use_private_canonical_handler_owner_visibility() -> None:
    calls: list[str] = []

    class PrivateInterceptor:
        async def intercept(
            self,
            context: CqrsInvocationContext,
            next: Callable[[], Awaitable[object]],
        ) -> object:
            calls.append(context.owner_module.module.__name__)
            return await next()

    class Handler:
        async def handle(self, command: Invoke) -> int:
            return command.value

    @module(
        providers=[
            ClassProvider(PrivateInterceptor),
            ClassProvider("handler", Handler),
        ],
        exports=["handler"],
    )
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[command_handler(Invoke, "handler")],
        options=CqrsModuleOptions(command_interceptors=(PrivateInterceptor,)),
        key="owner",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "owner"))
    assert isinstance(commands, CommandBus)
    assert await commands.execute(Invoke(5)) == 5
    assert calls == ["Feature"]
    await application.close()


@pytest.mark.asyncio
async def test_factory_handler_uses_only_explicit_interceptor_metadata() -> None:
    calls: list[str] = []
    ignored = RecordingInterceptor("ignored", calls)
    explicit = RecordingInterceptor("explicit", calls)

    @use_cqrs_interceptors(ignored)
    class Handler:
        async def handle(self, command: Invoke) -> int:
            calls.append("terminal")
            return command.value

    def create_handler() -> Handler:
        return Handler()

    @module(
        providers=[
            FactoryProvider("factory-handler", create_handler, scope=Scope.REQUEST),
            FactoryProvider(
                "factory-interceptor", lambda: explicit, scope=Scope.REQUEST
            ),
        ],
        exports=["factory-handler"],
    )
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[
            command_handler(
                Invoke,
                "factory-handler",
                interceptors=[
                    CqrsInterceptorBinding(
                        "factory-interceptor", CqrsInterceptorPhase.OUTER
                    )
                ],
            )
        ],
        key="factory-pipeline",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(
        CommandBus, module=(CqrsModule, "factory-pipeline")
    )
    assert isinstance(commands, CommandBus)
    assert calls == []
    assert await commands.execute(Invoke(3)) == 3
    assert calls == ["explicit:before", "terminal", "explicit:after"]
    await application.close()


@pytest.mark.asyncio
async def test_override_metadata_comes_from_final_class_implementation() -> None:
    calls: list[str] = []
    original_interceptor = RecordingInterceptor("original", calls)
    replacement_interceptor = RecordingInterceptor("replacement", calls)

    @use_cqrs_interceptors(original_interceptor)
    class Original:
        async def handle(self, command: Invoke) -> int:
            return -1

    @use_cqrs_interceptors(replacement_interceptor)
    class Replacement:
        async def handle(self, command: Invoke) -> int:
            calls.append("terminal")
            return command.value

    @module(providers=[ClassProvider(Original)], exports=[Original])
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[command_handler(Invoke, Original)],
        key="override-pipeline",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    builder = TestingModule.create(Root)
    builder.override_provider(Original, module=Feature).use_class(Replacement)
    application = await builder.compile()
    commands = await application.resolve(
        CommandBus, module=(CqrsModule, "override-pipeline")
    )
    assert isinstance(commands, CommandBus)
    assert await commands.execute(Invoke(4)) == 4
    assert calls == ["replacement:before", "terminal", "replacement:after"]
    await application.close()


@pytest.mark.asyncio
async def test_dynamic_owner_identity_qualifies_context_and_visibility() -> None:
    contexts: list[CqrsInvocationContext] = []

    class PrivateInterceptor:
        async def intercept(self, context, next):
            contexts.append(context)
            return await next()

    class Handler:
        async def handle(self, command: Invoke) -> int:
            return command.value

    class Feature:
        pass

    dynamic = DeferredModule(
        Feature,
        "blue",
        lambda: ModuleSpec(
            providers=[ClassProvider(PrivateInterceptor), ClassProvider(Handler)],
            exports=[Handler],
        ),
    )
    cqrs = CqrsModule.for_root(
        imports=[dynamic],
        handlers=[command_handler(Invoke, Handler)],
        options=CqrsModuleOptions(command_interceptors=(PrivateInterceptor,)),
        key="dynamic-pipeline",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(
        CommandBus, module=(CqrsModule, "dynamic-pipeline")
    )
    assert isinstance(commands, CommandBus)
    assert await commands.execute(Invoke(2)) == 2
    assert contexts[0].owner_module == ModuleId(Feature, "blue")
    assert contexts[0].module_id == f"{Feature.__qualname__}[blue]"
    await application.close()


@pytest.mark.asyncio
async def test_provider_interceptors_follow_normal_scope_semantics() -> None:
    constructions = {"singleton": 0, "request": 0, "transient": 0}

    class SingletonInterceptor:
        def __init__(self) -> None:
            constructions["singleton"] += 1

        async def intercept(self, context, next):
            del context
            return await next()

    class RequestInterceptor:
        def __init__(self) -> None:
            constructions["request"] += 1

        async def intercept(self, context, next):
            del context
            return await next()

    class TransientInterceptor:
        def __init__(self) -> None:
            constructions["transient"] += 1

        async def intercept(self, context, next):
            del context
            return await next()

    class Handler:
        async def handle(self, command: Invoke) -> int:
            return command.value

    @module(
        providers=[
            ClassProvider(SingletonInterceptor),
            ClassProvider(RequestInterceptor, scope=Scope.REQUEST),
            ClassProvider(TransientInterceptor, scope=Scope.TRANSIENT),
            ClassProvider(Handler),
        ],
        exports=[Handler],
    )
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[command_handler(Invoke, Handler)],
        options=CqrsModuleOptions(
            command_interceptors=(
                SingletonInterceptor,
                RequestInterceptor,
                TransientInterceptor,
            )
        ),
        key="scopes",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "scopes"))
    assert isinstance(commands, CommandBus)
    assert constructions == {"singleton": 1, "request": 0, "transient": 0}
    assert await commands.execute(Invoke(1)) == 1
    assert await commands.execute(Invoke(2)) == 2
    assert constructions == {"singleton": 1, "request": 2, "transient": 2}
    await application.close()


class FirstMappedError(RuntimeError):
    pass


class SecondMappedError(RuntimeError):
    pass


@pytest.mark.asyncio
async def test_completion_mappers_freeze_and_compose_in_reverse_after_scope() -> None:
    calls: list[tuple[str, BaseException | None]] = []
    captured: list[CqrsInvocationCompletion] = []

    class CompletionInterceptor:
        async def intercept(self, context, next):
            captured.append(context.completion)

            def first(completion, error):
                assert completion.result == 8
                assert completion.result_available
                assert completion.body_error is None
                assert completion.scope_error is None
                calls.append(("first", error))
                return FirstMappedError("first")

            def second(completion, error):
                assert completion.result_available
                calls.append(("second", error))
                return SecondMappedError("second")

            context.completion.register("first", first)
            context.completion.register("second", second)
            return await next()

    class Handler:
        async def handle(self, command: Invoke) -> int:
            return command.value

    @module(providers=[ClassProvider(Handler)], exports=[Handler])
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[command_handler(Invoke, Handler)],
        options=CqrsModuleOptions(command_interceptors=(CompletionInterceptor(),)),
        key="completion-order",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(
        CommandBus, module=(CqrsModule, "completion-order")
    )
    assert isinstance(commands, CommandBus)
    with pytest.raises(FirstMappedError, match="first"):
        await commands.execute(Invoke(8))
    assert calls[0] == ("second", None)
    assert isinstance(calls[1][1], SecondMappedError)
    with pytest.raises(CqrsPipelineStateError, match="frozen"):
        captured[0].register("late", lambda completion, error: error)
    await application.close()


@pytest.mark.asyncio
async def test_completion_can_map_cleanup_failure_after_successful_result() -> None:
    observed: list[CqrsScopeCompletion] = []

    class Resource:
        pass

    def resource_factory():
        @asynccontextmanager
        async def resource() -> AsyncIterator[Resource]:
            try:
                yield Resource()
            finally:
                raise RuntimeError("cleanup failed")

        return resource()

    class CompletionInterceptor:
        async def intercept(self, context, next):
            def map_cleanup(completion, error):
                observed.append(completion)
                assert isinstance(error, ScopeFinalizationError)
                return FirstMappedError("mapped cleanup")

            context.completion.register("cleanup", map_cleanup)
            return await next()

    class Handler:
        def __init__(self, resource: Resource) -> None:
            self.resource = resource

        async def handle(self, command: Invoke) -> int:
            return command.value

    @module(
        providers=[
            FactoryProvider(Resource, resource_factory, scope=Scope.REQUEST),
            ClassProvider(Handler, scope=Scope.REQUEST),
        ],
        exports=[Handler],
    )
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[command_handler(Invoke, Handler)],
        options=CqrsModuleOptions(command_interceptors=(CompletionInterceptor(),)),
        key="cleanup-result",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(
        CommandBus, module=(CqrsModule, "cleanup-result")
    )
    assert isinstance(commands, CommandBus)
    with pytest.raises(FirstMappedError, match="mapped cleanup") as captured:
        await commands.execute(Invoke(6))
    assert isinstance(captured.value.__cause__, ScopeFinalizationError)
    assert len(observed) == 1
    assert observed[0].result == 6
    assert observed[0].result_available
    assert observed[0].body_error is None
    assert observed[0].scope_error is captured.value.__cause__
    await application.close()


@pytest.mark.asyncio
async def test_completion_observes_body_and_cleanup_errors_after_cleanup() -> None:
    observations: list[CqrsScopeCompletion] = []
    cleanup_finished = False

    class Resource:
        pass

    def resource_factory():
        @asynccontextmanager
        async def resource() -> AsyncIterator[Resource]:
            nonlocal cleanup_finished
            try:
                yield Resource()
            finally:
                cleanup_finished = True
                raise RuntimeError("cleanup failed")

        return resource()

    class CompletionInterceptor:
        async def intercept(self, context, next):
            def observe(completion, error):
                assert cleanup_finished
                assert isinstance(error, ScopeFinalizationError)
                observations.append(completion)
                return error

            context.completion.register("observe", observe)
            return await next()

    class Handler:
        def __init__(self, resource: Resource) -> None:
            self.resource = resource

        async def handle(self, command: Invoke) -> int:
            raise ValueError("body failed")

    @module(
        providers=[
            FactoryProvider(Resource, resource_factory, scope=Scope.REQUEST),
            ClassProvider(Handler, scope=Scope.REQUEST),
        ],
        exports=[Handler],
    )
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[command_handler(Invoke, Handler)],
        options=CqrsModuleOptions(command_interceptors=(CompletionInterceptor(),)),
        key="cleanup",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "cleanup"))
    assert isinstance(commands, CommandBus)
    with pytest.raises(ScopeFinalizationError) as captured:
        await commands.execute(Invoke(1))
    assert isinstance(captured.value.body_error, ValueError)
    assert len(captured.value.cleanup_errors) == 1
    assert len(observations) == 1
    completion = observations[0]
    assert not completion.result_available
    assert completion.result is None
    assert isinstance(completion.body_error, ValueError)
    assert completion.scope_error is captured.value
    await application.close()


@pytest.mark.asyncio
async def test_completion_preserves_cancellation_with_cleanup_failure() -> None:
    observed: list[tuple[CqrsScopeCompletion, BaseException | None]] = []

    class Resource:
        pass

    def resource_factory():
        @asynccontextmanager
        async def resource() -> AsyncIterator[Resource]:
            try:
                yield Resource()
            finally:
                raise RuntimeError("cleanup failed")

        return resource()

    class CompletionInterceptor:
        async def intercept(self, context, next):
            def observe(completion, error):
                observed.append((completion, error))
                return error

            context.completion.register("cancellation", observe)
            return await next()

    class Handler:
        def __init__(self, resource: Resource) -> None:
            self.resource = resource

        async def handle(self, command: Invoke) -> int:
            raise asyncio.CancelledError("cancelled")

    @module(
        providers=[
            FactoryProvider(Resource, resource_factory, scope=Scope.REQUEST),
            ClassProvider(Handler, scope=Scope.REQUEST),
        ],
        exports=[Handler],
    )
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[command_handler(Invoke, Handler)],
        options=CqrsModuleOptions(command_interceptors=(CompletionInterceptor(),)),
        key="cleanup-cancellation",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(
        CommandBus, module=(CqrsModule, "cleanup-cancellation")
    )
    assert isinstance(commands, CommandBus)
    with pytest.raises(ScopeCancellationError) as captured:
        await commands.execute(Invoke(1))
    completion, current = observed[0]
    assert completion.scope_error is captured.value
    assert completion.body_error is captured.value.cancellation
    assert current is captured.value
    await application.close()


@pytest.mark.asyncio
async def test_completion_rejects_duplicates_async_mappers_and_suppression() -> None:
    class InvalidCompletionInterceptor:
        async def intercept(self, context, next):
            def mapper(completion, error):
                del completion, error
                return None

            context.completion.register("duplicate", mapper)
            with pytest.raises(CqrsPipelineStateError, match="already registered"):
                context.completion.register("duplicate", mapper)

            async def async_mapper(completion, error):
                return error

            with pytest.raises(CqrsPipelineStateError, match="synchronous"):
                context.completion.register("async", async_mapper)
            return await next()

    class Handler:
        async def handle(self, command: Invoke) -> int:
            raise RuntimeError("handler failed")

    @module(providers=[ClassProvider(Handler)], exports=[Handler])
    class Feature:
        pass

    cqrs = CqrsModule.for_root(
        imports=[Feature],
        handlers=[command_handler(Invoke, Handler)],
        options=CqrsModuleOptions(
            command_interceptors=(InvalidCompletionInterceptor(),)
        ),
        key="completion-invalid",
    )

    @module(imports=[cqrs])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    commands = await application.resolve(
        CommandBus, module=(CqrsModule, "completion-invalid")
    )
    assert isinstance(commands, CommandBus)
    with pytest.raises(CqrsPipelineStateError, match="cannot suppress"):
        await commands.execute(Invoke(1))
    await application.close()
