from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Annotated
from uuid import uuid4

import pytest
from nestpy import (
    ExecutionContext,
    ModuleId,
    PipelineResult,
    ProviderRef,
    ScopeFinalizationError,
    Token,
    use_filter,
    use_guard,
    use_interceptor,
    use_pipe,
)

from nestpy_microservices import (
    RESULT_MISSING,
    Context,
    EventContext,
    EventDispatchMode,
    MessageConfigurationError,
    MessageInvocation,
    MessageLimits,
    MessagePipelineExecutor,
    MessageRetryableError,
    Payload,
    PipelinePlan,
    RpcContext,
    ServiceIdentity,
    SettlementRecommendation,
    WireSizeLimitError,
    compile_controller_message_handlers,
    event_handler,
    rpc,
)

MODULE_ID = ModuleId(object)


class Resolver:
    def __init__(self, values: dict[Token, object]) -> None:
        self.values = values

    async def resolve(self, token: Token) -> object:
        return self.values[token]

    async def resolve_ref(self, ref: ProviderRef) -> object:
        return self.values[ref.token]


class Scopes:
    def __init__(self, resolver: Resolver, events: list[str]) -> None:
        self.resolver = resolver
        self.events = events

    @property
    def application_id(self) -> str:
        return "test-app"

    @property
    def module_id(self) -> ModuleId:
        return MODULE_ID

    def open(self):
        raise NotImplementedError

    async def run(self, operation):
        return await self.run_in(MODULE_ID, operation)

    async def run_in(self, module_id: ModuleId, operation):
        assert module_id == MODULE_ID
        self.events.append("scope-open")
        result = await operation(self.resolver)
        self.events.append("scope-close")
        return result


class GuardStage:
    def __init__(self, events: list[str], allowed: bool = True) -> None:
        self.events = events
        self.allowed = allowed

    async def can_activate(self, context: ExecutionContext) -> bool:
        self.events.append(f"guard:{context.execution_kind}")
        return self.allowed


class PipeStage:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def transform(self, value: object, metadata) -> object:
        self.events.append(f"pipe:{metadata.binding_kind}")
        return str(value).upper()


class InterceptorStage:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def intercept(self, context, next):
        self.events.append("interceptor:before")
        result = await next()
        self.events.append("interceptor:after")
        return result


class FilterStage:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def catch(self, error: Exception, context) -> PipelineResult:
        self.events.append(type(error).__name__)
        return PipelineResult.from_value("fallback")


def test_invocation_runs_ordered_pipeline_and_closes_scope_before_completion() -> None:
    events: list[str] = []
    guard = GuardStage(events)
    pipe = PipeStage(events)
    interceptor = InterceptorStage(events)

    class Controller:
        @rpc("handle")
        @use_guard(guard)
        @use_pipe(pipe)
        @use_interceptor(interceptor)
        async def handle(
            self,
            payload: Annotated[str, Payload()],
            context: Annotated[RpcContext, Context()],
        ) -> str:
            assert context.execution_kind == "rpc"
            events.append("handler")
            return payload

    plan = compile_controller_message_handlers(MODULE_ID, Controller)[0]
    resolver = Resolver({Controller: Controller()})
    scopes = Scopes(resolver, events)
    invocation = MessageInvocation(
        application_id="test-app",
        message_id=uuid4(),
        correlation_id=uuid4(),
        payload="hello",
        headers={},
        metadata={"routing_key": "handle"},
    )

    async def encode(value: object) -> str:
        events.append("encode")
        return f"encoded:{value}"

    completion = asyncio.run(
        MessagePipelineExecutor(PipelinePlan(guards=(GuardStage(events),))).invoke(
            scopes, plan, invocation, encode_result=encode
        )
    )

    assert completion.succeeded
    assert completion.encoded_response == "encoded:HELLO"
    assert events == [
        "scope-open",
        "guard:rpc",
        "guard:rpc",
        "pipe:payload",
        "interceptor:before",
        "handler",
        "interceptor:after",
        "encode",
        "scope-close",
    ]


def test_guard_denial_is_terminal_rejection_without_handler_execution() -> None:
    events: list[str] = []
    denied = GuardStage(events, allowed=False)

    class Controller:
        @rpc("denied")
        @use_guard(denied)
        async def handle(self, payload: Annotated[object, Payload()]) -> object:
            events.append("handler")
            return payload

    plan = compile_controller_message_handlers(MODULE_ID, Controller)[0]
    completion = asyncio.run(
        MessagePipelineExecutor().invoke(
            Scopes(Resolver({Controller: Controller()}), events),
            plan,
            MessageInvocation("app", uuid4(), uuid4(), "body", {}, {}),
            encode_result=lambda value: value,
        )
    )

    assert completion.recommendation is SettlementRecommendation.REJECT
    assert isinstance(completion.body_error, Exception)
    assert events == ["scope-open", "guard:rpc", "scope-close"]


def test_filter_replaces_handler_error_and_allows_ack() -> None:
    events: list[str] = []
    filter_stage = FilterStage(events)

    class Controller:
        @rpc("filtered")
        @use_filter(filter_stage)
        async def handle(self, payload: Annotated[object, Payload()]) -> object:
            raise MessageRetryableError("try again")

    plan = compile_controller_message_handlers(MODULE_ID, Controller)[0]
    completion = asyncio.run(
        MessagePipelineExecutor().invoke(
            Scopes(Resolver({Controller: Controller()}), events),
            plan,
            MessageInvocation("app", uuid4(), uuid4(), "body", {}, {}),
            encode_result=lambda value: f"encoded:{value}",
        )
    )

    assert completion.succeeded
    assert completion.encoded_response == "encoded:fallback"
    assert events == ["scope-open", "MessageRetryableError", "scope-close"]


def test_filter_resolution_failure_falls_through_to_later_filter() -> None:
    events: list[str] = []

    class MissingFilter:
        async def catch(self, error, context):
            raise AssertionError("missing filter was resolved")

    class Controller:
        @rpc("filtered-later")
        async def handle(self, payload: Annotated[object, Payload()]) -> object:
            raise MessageRetryableError("try again")

    plan = compile_controller_message_handlers(MODULE_ID, Controller)[0]
    plan = replace(
        plan,
        method_pipeline=PipelinePlan(filters=(MissingFilter, FilterStage(events))),
    )
    completion = asyncio.run(
        MessagePipelineExecutor().invoke(
            Scopes(Resolver({Controller: Controller()}), events),
            plan,
            MessageInvocation("app", uuid4(), uuid4(), "body", {}, {}),
            encode_result=lambda value: value,
        )
    )

    assert completion.succeeded
    assert completion.result == "fallback"


def test_filter_response_is_rejected() -> None:
    class ResponseFilter:
        async def catch(self, error, context):
            return PipelineResult.from_response("native")

    class Controller:
        @rpc("filtered-response")
        async def handle(self, payload: Annotated[object, Payload()]) -> object:
            raise MessageRetryableError("try again")

    plan = compile_controller_message_handlers(MODULE_ID, Controller)[0]
    plan = replace(plan, method_pipeline=PipelinePlan(filters=(ResponseFilter(),)))
    completion = asyncio.run(
        MessagePipelineExecutor().invoke(
            Scopes(Resolver({Controller: Controller()}), []),
            plan,
            MessageInvocation("app", uuid4(), uuid4(), "body", {}, {}),
            encode_result=lambda value: value,
        )
    )

    assert completion.recommendation is SettlementRecommendation.REJECT
    assert isinstance(completion.body_error, MessageConfigurationError)
    assert completion.scope_error is None


def test_invocation_metadata_applies_size_limits() -> None:
    with pytest.raises(WireSizeLimitError):
        MessageInvocation(
            "app",
            uuid4(),
            None,
            "body",
            {"large": "x" * 20},
            {},
            limits=MessageLimits(max_header_bytes=10),
        )


def test_custom_metadata_limits_reach_message_context() -> None:
    class Controller:
        @rpc("large-metadata")
        async def handle(self, context: Annotated[RpcContext, Context()]) -> int:
            value = context.metadata["large"]
            assert isinstance(value, str)
            return len(value)

    plan = compile_controller_message_handlers(MODULE_ID, Controller)[0]
    value = "x" * 70_000
    completion = asyncio.run(
        MessagePipelineExecutor().invoke(
            Scopes(Resolver({Controller: Controller()}), []),
            plan,
            MessageInvocation(
                "app",
                uuid4(),
                None,
                "body",
                {},
                {"large": value},
                limits=MessageLimits(max_header_bytes=80_000),
            ),
            encode_result=lambda result: result,
        )
    )

    assert completion.succeeded
    assert completion.result == len(value)


def test_unqualified_global_provider_binding_is_rejected() -> None:
    class GlobalGuard:
        async def can_activate(self, context) -> bool:
            return True

    class Controller:
        @rpc("global-provider")
        async def handle(self, payload: Annotated[object, Payload()]) -> object:
            return payload

    plan = compile_controller_message_handlers(MODULE_ID, Controller)[0]
    completion = asyncio.run(
        MessagePipelineExecutor(PipelinePlan(guards=(GlobalGuard,))).invoke(
            Scopes(
                Resolver({Controller: Controller(), GlobalGuard: GlobalGuard()}),
                [],
            ),
            plan,
            MessageInvocation("app", uuid4(), None, "body", {}, {}),
            encode_result=lambda result: result,
        )
    )

    assert completion.recommendation is SettlementRecommendation.REJECT
    assert isinstance(completion.body_error, MessageConfigurationError)


def test_scope_finalization_failure_is_not_reported_as_success() -> None:
    events: list[str] = []

    class Controller:
        @rpc("cleanup-fails")
        async def handle(self, payload: Annotated[object, Payload()]) -> object:
            return payload

    class FailingScopes(Scopes):
        async def run_in(self, module_id: ModuleId, operation):
            await operation(self.resolver)
            raise ScopeFinalizationError(None, (RuntimeError("cleanup"),))

    plan = compile_controller_message_handlers(MODULE_ID, Controller)[0]
    completion = asyncio.run(
        MessagePipelineExecutor().invoke(
            FailingScopes(Resolver({Controller: Controller()}), events),
            plan,
            MessageInvocation("app", uuid4(), uuid4(), "body", {}, {}),
            encode_result=lambda value: value,
        )
    )

    assert completion.recommendation is SettlementRecommendation.RETRY
    assert completion.scope_error is not None
    assert not completion.succeeded


def test_cancellation_is_preserved() -> None:
    class Controller:
        @rpc("cancelled")
        async def handle(self, payload: Annotated[object, Payload()]) -> object:
            raise asyncio.CancelledError()

    plan = compile_controller_message_handlers(MODULE_ID, Controller)[0]
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            MessagePipelineExecutor().invoke(
                Scopes(Resolver({Controller: Controller()}), []),
                plan,
                MessageInvocation("app", uuid4(), uuid4(), "body", {}, {}),
                encode_result=lambda value: value,
            )
        )


def test_event_success_does_not_encode_a_result() -> None:
    class Controller:
        @event_handler(
            ServiceIdentity("kinker", "members", 1),
            "profile-created",
            schema_version=1,
            mode=EventDispatchMode.SERVICE_POOL,
            subscription="notify",
        )
        async def handle(self, context: Annotated[EventContext, Context()]) -> None:
            assert context.execution_kind == "event"
            return None

    plan = compile_controller_message_handlers(MODULE_ID, Controller)[0]
    completion = asyncio.run(
        MessagePipelineExecutor().invoke(
            Scopes(Resolver({Controller: Controller()}), []),
            plan,
            MessageInvocation("app", uuid4(), None, "body", {}, {}),
            encode_result=lambda value: (_ for _ in ()).throw(
                AssertionError("event result must not be encoded")
            ),
        )
    )

    assert completion.succeeded
    assert completion.encoded_response is RESULT_MISSING
