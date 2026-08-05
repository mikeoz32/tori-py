"""Scoped message invocation and settlement-neutral completion results."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, cast
from uuid import UUID

import msgspec
from nestpy import (
    ArgumentMetadata,
    ExceptionFilter,
    Guard,
    Interceptor,
    Pipe,
    PipelineResult,
    PipelineStateError,
    ProviderRef,
    ScopedResolver,
    ScopeFinalizationError,
    WorkScopeFactory,
)

from nestpy_microservices.contexts import EventContext, MessageContext, RpcContext
from nestpy_microservices.errors import (
    MessageAuthorizationError,
    MessageConfigurationError,
    MessageInvocationError,
    MessageRejectedError,
    MessageRetryableError,
)
from nestpy_microservices.identities import (
    MessageLimits,
    require_utc,
    require_uuid,
    utc_now,
)
from nestpy_microservices.plans import (
    EventHandlerPlan,
    MessageParameterPlan,
    PipelinePlan,
    RpcHandlerPlan,
)
from nestpy_microservices.wire import RESULT_MISSING, freeze_headers


class SettlementRecommendation(StrEnum):
    """Transport-neutral recommendation after one delivery attempt."""

    ACK = "ack"
    RETRY = "retry"
    REJECT = "reject"
    UNSETTLED = "unsettled"


@dataclass(frozen=True, slots=True)
class MessageInvocation:
    """Decoded transport input supplied to one scoped handler attempt."""

    application_id: str
    message_id: UUID
    correlation_id: UUID | None
    payload: object
    headers: Mapping[str, object]
    metadata: Mapping[str, object]
    received_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    attempt: int = 1
    redelivered: bool = False
    native: object | None = None
    limits: MessageLimits = field(default_factory=MessageLimits)

    def __post_init__(self) -> None:
        if not isinstance(self.application_id, str) or not self.application_id:
            raise ValueError("application_id must be a non-empty string")
        if not isinstance(self.attempt, int) or self.attempt <= 0:
            raise ValueError("attempt must be a positive integer")
        require_uuid(self.message_id, "message_id")
        if self.correlation_id is not None:
            require_uuid(self.correlation_id, "correlation_id")
        require_utc(self.received_at, "received_at")
        if self.expires_at is not None:
            require_utc(self.expires_at, "expires_at")
        object.__setattr__(self, "headers", freeze_headers(self.headers, self.limits))
        object.__setattr__(self, "metadata", freeze_headers(self.metadata, self.limits))


@dataclass(frozen=True, slots=True)
class InvocationCompletion:
    """Final invocation facts available to a transport settlement adapter."""

    recommendation: SettlementRecommendation
    result: object = RESULT_MISSING
    encoded_response: object = RESULT_MISSING
    body_error: Exception | None = None
    scope_error: BaseException | None = None

    @property
    def succeeded(self) -> bool:
        return (
            self.recommendation is SettlementRecommendation.ACK
            and self.body_error is None
            and self.scope_error is None
        )


class MessagePipelineExecutor:
    """Execute message guards, binders, pipes, interceptors, and filters."""

    def __init__(self, global_pipeline: PipelinePlan | None = None) -> None:
        self.global_pipeline = global_pipeline or PipelinePlan()

    async def run(
        self,
        plan: RpcHandlerPlan | EventHandlerPlan,
        context: MessageContext,
        resolver: ScopedResolver,
        invocation: MessageInvocation,
        *,
        encode_result: Callable[[object], Awaitable[object] | object],
        prepared_arguments: Mapping[str, object] | None = None,
    ) -> InvocationCompletion:
        try:
            pipeline_result = await self._run_pipeline(
                plan,
                context,
                resolver,
                invocation,
                prepared_arguments=prepared_arguments,
            )
            if pipeline_result.is_response:
                raise MessageConfigurationError(
                    "message interceptors cannot return native responses"
                )
            result = _validate_result(pipeline_result.value, plan.return_annotation)
            if isinstance(plan, EventHandlerPlan) and result is not None:
                raise MessageConfigurationError("event handlers must return None")
            encoded = (
                RESULT_MISSING
                if isinstance(plan, EventHandlerPlan)
                else encode_result(result)
            )
            if inspect.isawaitable(encoded):
                encoded = await encoded
            return InvocationCompletion(
                recommendation=SettlementRecommendation.ACK,
                result=result,
                encoded_response=encoded,
            )
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            replacement_result = await self._run_filters(plan, context, resolver, error)
            if replacement_result is not RESULT_MISSING:
                assert isinstance(replacement_result, PipelineResult)
                if replacement_result.is_response:
                    error = MessageConfigurationError(
                        "message filters cannot return native responses"
                    )
                else:
                    try:
                        replacement = _validate_result(
                            replacement_result.value, plan.return_annotation
                        )
                        if (
                            isinstance(plan, EventHandlerPlan)
                            and replacement is not None
                        ):
                            raise MessageConfigurationError(
                                "event handlers must return None"
                            )
                        encoded = (
                            RESULT_MISSING
                            if isinstance(plan, EventHandlerPlan)
                            else await _encode_result(encode_result, replacement)
                        )
                    except MessageConfigurationError as replacement_error:
                        error = replacement_error
                    else:
                        return InvocationCompletion(
                            recommendation=SettlementRecommendation.ACK,
                            result=replacement,
                            encoded_response=encoded,
                        )
            return InvocationCompletion(
                recommendation=_recommendation(error, plan),
                body_error=error,
            )

    async def invoke(
        self,
        work_scopes: WorkScopeFactory,
        plan: RpcHandlerPlan | EventHandlerPlan,
        invocation: MessageInvocation,
        *,
        encode_result: Callable[[object], Awaitable[object] | object],
    ) -> InvocationCompletion:
        """Run one attempt through a fresh exact-owner Nestpy work scope."""

        try:
            prepared_arguments = _prepare_arguments(plan.parameters, invocation)
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            return InvocationCompletion(
                recommendation=SettlementRecommendation.REJECT,
                body_error=error,
            )

        async def operation(resolver: ScopedResolver) -> InvocationCompletion:
            context = _make_context(plan, resolver, invocation)
            return await self.run(
                plan,
                context,
                resolver,
                invocation,
                encode_result=encode_result,
                prepared_arguments=prepared_arguments,
            )

        try:
            return await work_scopes.run_in(plan.module_id, operation)
        except ScopeFinalizationError as error:
            body_error = (
                error.body_error if isinstance(error.body_error, Exception) else None
            )
            return InvocationCompletion(
                recommendation=_scope_recommendation(body_error),
                body_error=body_error,
                scope_error=error,
            )
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            return InvocationCompletion(
                recommendation=_scope_recommendation(error),
                scope_error=error,
            )

    async def _run_pipeline(
        self,
        plan: RpcHandlerPlan | EventHandlerPlan,
        context: MessageContext,
        resolver: ScopedResolver,
        invocation: MessageInvocation,
        prepared_arguments: Mapping[str, object] | None = None,
    ) -> PipelineResult:
        await self._run_guards(plan, context, resolver)
        arguments = await self._bind_arguments(
            plan.parameters,
            context,
            resolver,
            invocation,
            prepared_arguments=prepared_arguments,
        )
        await self._run_pipes(plan, context, resolver, arguments)
        return await self._run_interceptors(
            plan,
            context,
            resolver,
            lambda: self._call_handler(plan, resolver, arguments),
        )

    async def _run_guards(
        self,
        plan: RpcHandlerPlan | EventHandlerPlan,
        context: MessageContext,
        resolver: ScopedResolver,
    ) -> None:
        for binding, provider_ref, allow_token_fallback in self._pipeline_entries(
            "guards", plan
        ):
            guard = await self._resolve_binding(
                resolver, binding, provider_ref, allow_token_fallback
            )
            if not await cast(Guard, guard).can_activate(context):
                raise MessageAuthorizationError("message guard denied execution")

    async def _bind_arguments(
        self,
        parameters: tuple[MessageParameterPlan, ...],
        context: MessageContext,
        resolver: ScopedResolver,
        invocation: MessageInvocation,
        *,
        prepared_arguments: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        arguments: dict[str, object] = {}
        for parameter in parameters:
            if parameter.kind in {"payload", "headers", "header"}:
                if prepared_arguments is None:
                    value = _prepare_argument(parameter, invocation)
                else:
                    value = prepared_arguments[parameter.name]
            elif parameter.kind == "context":
                value = context
            elif parameter.kind == "inject":
                if parameter.token is None:
                    raise MessageConfigurationError("inject parameter has no token")
                value = await self._resolve_ref(
                    resolver, parameter.provider_ref, parameter.token
                )
            else:  # pragma: no cover - compiler rejects unknown kinds
                raise MessageConfigurationError(
                    f"unsupported message parameter kind {parameter.kind!r}"
                )
            arguments[parameter.name] = (
                parameter.default
                if value is RESULT_MISSING and parameter.has_default
                else value
            )
            if arguments[parameter.name] is RESULT_MISSING:
                raise MessageConfigurationError(
                    f"required message argument {parameter.name!r} is missing"
                )
        return arguments

    async def _run_pipes(
        self,
        plan: RpcHandlerPlan | EventHandlerPlan,
        context: MessageContext,
        resolver: ScopedResolver,
        arguments: dict[str, object],
    ) -> None:
        pipes: list[object] = []
        for binding, provider_ref, allow_token_fallback in self._pipeline_entries(
            "pipes", plan
        ):
            pipes.append(
                await self._resolve_binding(
                    resolver, binding, provider_ref, allow_token_fallback
                )
            )
        for parameter in plan.parameters:
            if parameter.kind in {"context", "inject"}:
                continue
            metadata = ArgumentMetadata(
                parameter_name=parameter.name,
                binding_kind=parameter.kind,
                source_name=parameter.source,
                annotation=parameter.annotation,
                route_id=plan.method_name,
                module_id=context.module_id or "",
            )
            for pipe in pipes:
                arguments[parameter.name] = await cast(Pipe, pipe).transform(
                    arguments[parameter.name], metadata
                )

    async def _run_interceptors(
        self,
        plan: RpcHandlerPlan | EventHandlerPlan,
        context: MessageContext,
        resolver: ScopedResolver,
        terminal: Callable[[], Awaitable[object]],
    ) -> PipelineResult:
        interceptors = self._pipeline_entries("interceptors", plan)

        async def dispatch(index: int) -> PipelineResult:
            if index == len(interceptors):
                return PipelineResult.from_value(await terminal())
            called = False

            async def next_once() -> PipelineResult:
                nonlocal called
                if called:
                    raise PipelineStateError(
                        "message interceptor next callback was called twice"
                    )
                called = True
                return await dispatch(index + 1)

            binding, provider_ref, allow_token_fallback = interceptors[index]
            interceptor = cast(
                Interceptor,
                await self._resolve_binding(
                    resolver, binding, provider_ref, allow_token_fallback
                ),
            )
            result = await interceptor.intercept(context, next_once)
            if not isinstance(result, PipelineResult):
                raise MessageConfigurationError(
                    "message interceptor must return PipelineResult"
                )
            return result

        return await dispatch(0)

    async def _run_filters(
        self,
        plan: RpcHandlerPlan | EventHandlerPlan,
        context: MessageContext,
        resolver: ScopedResolver,
        error: Exception,
    ) -> PipelineResult | object:
        for binding, provider_ref, allow_token_fallback in self._pipeline_entries(
            "filters", plan
        ):
            try:
                filter_ = cast(
                    ExceptionFilter,
                    await self._resolve_binding(
                        resolver, binding, provider_ref, allow_token_fallback
                    ),
                )
                result = await filter_.catch(error, context)
            except BaseException as filter_error:
                if not isinstance(filter_error, Exception):
                    raise
                continue
            if isinstance(result, PipelineResult):
                return result
        return RESULT_MISSING

    def _pipeline_entries(
        self,
        kind: str,
        plan: RpcHandlerPlan | EventHandlerPlan,
    ) -> tuple[tuple[object, ProviderRef | None, bool], ...]:
        local = plan.controller_pipeline
        method = plan.method_pipeline
        values: list[tuple[object, ProviderRef | None, bool]] = []
        for pipeline in (self.global_pipeline, local, method):
            allow_token_fallback = pipeline is not self.global_pipeline
            bindings = getattr(pipeline, kind)
            refs = [
                ref
                for binding_kind, ref in pipeline.qualified_provider_refs
                if binding_kind == kind
            ]
            ref_index = 0
            for binding in bindings:
                if isinstance(binding, (str, type)):
                    ref = refs[ref_index] if ref_index < len(refs) else None
                    ref_index += 1
                    values.append((binding, ref, allow_token_fallback))
                else:
                    values.append((binding, None, allow_token_fallback))
        return tuple(values)

    async def _resolve_binding(
        self,
        resolver: ScopedResolver,
        binding: object,
        provider_ref: ProviderRef | None,
        allow_token_fallback: bool,
    ) -> object:
        if provider_ref is None:
            if isinstance(binding, (str, type)) and not allow_token_fallback:
                raise MessageConfigurationError(
                    "global provider bindings must be compiler-qualified"
                )
            return (
                binding
                if not isinstance(binding, (str, type))
                else await resolver.resolve(binding)
            )
        return await self._resolve_ref(resolver, provider_ref, provider_ref.token)

    async def _resolve_ref(
        self,
        resolver: ScopedResolver,
        provider_ref: ProviderRef | None,
        fallback_token: object,
    ) -> object:
        if provider_ref is None:
            return await resolver.resolve(cast(Any, fallback_token))
        return await resolver.resolve_ref(provider_ref)

    async def _call_handler(
        self,
        plan: RpcHandlerPlan | EventHandlerPlan,
        resolver: ScopedResolver,
        arguments: dict[str, object],
    ) -> object:
        controller = await self._resolve_ref(
            resolver, plan.controller_ref, plan.controller
        )
        handler = getattr(controller, plan.method_name, None)
        if not callable(handler):
            raise MessageConfigurationError(
                "compiled controller handler is not callable"
            )
        result = handler(**arguments)
        return await result if inspect.isawaitable(result) else result


def _make_context(
    plan: RpcHandlerPlan | EventHandlerPlan,
    resolver: ScopedResolver,
    invocation: MessageInvocation,
) -> MessageContext:
    context_type = EventContext if isinstance(plan, EventHandlerPlan) else RpcContext
    return context_type(
        application=invocation.application_id,
        module_identity=plan.module_id,
        handler_id=f"{plan.controller.__qualname__}.{plan.method_name}",
        correlation_id=invocation.correlation_id,
        scope_resolver=resolver,
        message_metadata=invocation.metadata,
        received_at=invocation.received_at,
        expires_at=invocation.expires_at,
        attempt=invocation.attempt,
        redelivered=invocation.redelivered,
        native_value=invocation.native,
        limits=invocation.limits,
    )


def _field(
    value: object,
    source: str | None,
    parameter: MessageParameterPlan,
) -> object:
    if source is None:
        return value
    if not isinstance(value, Mapping) or source not in value:
        return parameter.default if parameter.has_default else RESULT_MISSING
    return cast(Mapping[str, object], value)[source]


def _prepare_arguments(
    parameters: tuple[MessageParameterPlan, ...],
    invocation: MessageInvocation,
) -> Mapping[str, object]:
    return {
        parameter.name: _prepare_argument(parameter, invocation)
        for parameter in parameters
        if parameter.kind in {"payload", "headers", "header"}
    }


def _prepare_argument(
    parameter: MessageParameterPlan,
    invocation: MessageInvocation,
) -> object:
    if parameter.kind == "payload":
        value = invocation.payload
        if parameter.source is not None:
            value = _field(value, parameter.source, parameter)
    elif parameter.kind == "headers":
        value = invocation.headers
    else:
        value = _field(invocation.headers, parameter.source, parameter)
    if value is RESULT_MISSING:
        if parameter.has_default:
            return parameter.default
        raise MessageRejectedError(
            f"required message argument {parameter.name!r} is missing"
        )
    if (
        parameter.annotation is inspect.Signature.empty
        or parameter.annotation is object
        or parameter.annotation is Any
    ):
        return value
    try:
        return msgspec.convert(value, type=cast(Any, parameter.annotation))
    except (TypeError, ValueError, msgspec.ValidationError) as error:
        raise MessageRejectedError(
            f"message argument {parameter.name!r} does not satisfy its annotation"
        ) from error


def _validate_result(value: object, annotation: object) -> object:
    if annotation is inspect.Signature.empty:
        return value
    try:
        return msgspec.convert(value, type=cast(Any, annotation))
    except (TypeError, ValueError, msgspec.ValidationError) as error:
        raise MessageConfigurationError(
            "handler result does not satisfy its declared return annotation"
        ) from error


async def _encode_result(
    encoder: Callable[[object], Awaitable[object] | object], value: object
) -> object:
    try:
        encoded = encoder(value)
        if inspect.isawaitable(encoded):
            encoded = await encoded
        return encoded
    except Exception as error:
        raise MessageConfigurationError("message result encoding failed") from error


def _recommendation(
    error: Exception,
    plan: RpcHandlerPlan | EventHandlerPlan,
) -> SettlementRecommendation:
    if isinstance(
        error,
        MessageAuthorizationError | MessageRejectedError | MessageConfigurationError,
    ):
        return SettlementRecommendation.REJECT
    if isinstance(error, MessageRetryableError):
        return SettlementRecommendation.RETRY
    if isinstance(error, MessageInvocationError):
        return SettlementRecommendation.REJECT
    return (
        SettlementRecommendation.RETRY
        if isinstance(plan, EventHandlerPlan)
        else SettlementRecommendation.REJECT
    )


def _scope_recommendation(error: Exception | None) -> SettlementRecommendation:
    del error
    return SettlementRecommendation.UNSETTLED


__all__ = [
    "InvocationCompletion",
    "MessageInvocation",
    "MessagePipelineExecutor",
    "SettlementRecommendation",
]
