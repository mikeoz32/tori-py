"""Transport-neutral scoped stream invocation pipeline."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import cast

from tori_py import (
    ArgumentMetadata,
    ExceptionFilter,
    Guard,
    Interceptor,
    Pipe,
    PipelineResult,
    PipelineStateError,
    ProviderRef,
    QualifiedScopedResolver,
    ScopedResolver,
    WorkScopeFactory,
)
from tori_py_persistent_streams_core import StoredRecord

from tori_py_persistent_streams.contexts import StreamContext
from tori_py_persistent_streams.contracts import StreamCodec
from tori_py_persistent_streams.errors import StreamInvocationError
from tori_py_persistent_streams.options import StreamBinding
from tori_py_persistent_streams.plans import (
    StreamHandlerPlan,
    StreamPipelinePlan,
)


class StreamPipelineExecutor:
    """Decode and execute one record; successful return is checkpoint eligibility."""

    def __init__(self, global_pipeline: StreamPipelinePlan | None = None) -> None:
        self.global_pipeline = global_pipeline or StreamPipelinePlan()

    async def invoke(
        self,
        work_scopes: WorkScopeFactory,
        plan: StreamHandlerPlan,
        binding: StreamBinding,
        record: StoredRecord,
    ) -> None:
        if len(record.payload) > binding.definition.limits.max_payload_bytes:
            raise StreamInvocationError("stream payload exceeds configured limit")
        try:
            codec = cast(StreamCodec, binding.codec)
            payload = codec.decode(record.payload, plan.payload_type)
        except Exception as error:
            raise StreamInvocationError("stream payload decoding failed") from error
        if not isinstance(payload, plan.payload_type):
            raise StreamInvocationError("stream codec returned the wrong payload type")

        async def operation(resolver: ScopedResolver) -> None:
            context = StreamContext(
                work_scopes.application_id,
                plan.module_id,
                plan.handler_id,
                plan.metadata.stream,
                plan.metadata.consumer_group,
                record.partition,
                record.offset,
                record.appended_at,
                record.record_id,
                record.headers,
                resolver,
                record,
            )
            try:
                await self._run(plan, context, resolver, payload, record)
            except Exception as error:
                await self._notify_filters(plan, context, resolver, error)
                raise

        await work_scopes.run_in(plan.module_id, operation)

    async def _run(
        self,
        plan: StreamHandlerPlan,
        context: StreamContext,
        resolver: ScopedResolver,
        payload: object,
        record: StoredRecord,
    ) -> None:
        for binding, ref, fallback in self._entries("guards", plan):
            guard = cast(Guard, await self._resolve(resolver, binding, ref, fallback))
            if not await guard.can_activate(context):
                raise StreamInvocationError("stream guard denied execution")
        arguments = await self._arguments(plan, context, resolver, payload, record)
        result = await self._interceptors(
            plan,
            context,
            resolver,
            lambda: self._call_handler(plan, resolver, arguments),
        )
        if result.is_response:
            raise StreamInvocationError("stream interceptors cannot return responses")
        if result.value is not None:
            raise StreamInvocationError("stream handlers must return None")

    async def _arguments(
        self,
        plan: StreamHandlerPlan,
        context: StreamContext,
        resolver: ScopedResolver,
        payload: object,
        record: StoredRecord,
    ) -> dict[str, object]:
        arguments: dict[str, object] = {}
        pipes = [
            cast(Pipe, await self._resolve(resolver, binding, ref, fallback))
            for binding, ref, fallback in self._entries("pipes", plan)
        ]
        for parameter in plan.parameters:
            if parameter.kind == "payload":
                value: object = payload
            elif parameter.kind == "context":
                value = context
            elif parameter.kind == "headers":
                value = record.headers
            elif parameter.kind == "header":
                if parameter.source not in record.headers:
                    if parameter.has_default:
                        value = parameter.default
                    else:
                        raise StreamInvocationError(
                            f"required stream header {parameter.source!r} is missing"
                        )
                else:
                    value = record.headers[cast(str, parameter.source)]
            elif parameter.kind == "partition":
                value = record.partition
            elif parameter.kind == "offset":
                value = record.offset
            else:
                if parameter.provider_ref is None:
                    raise StreamInvocationError("stream injection is not qualified")
                value = await self._resolve_ref(resolver, parameter.provider_ref)
            if parameter.kind not in {"context", "inject"}:
                metadata = ArgumentMetadata(
                    parameter.name,
                    parameter.kind,
                    parameter.source,
                    parameter.annotation,
                    plan.handler_id,
                    context.module_id,
                )
                for pipe in pipes:
                    value = await pipe.transform(value, metadata)
            arguments[parameter.name] = value
        return arguments

    async def _interceptors(
        self,
        plan: StreamHandlerPlan,
        context: StreamContext,
        resolver: ScopedResolver,
        terminal: Callable[[], Awaitable[object]],
    ) -> PipelineResult:
        entries = self._entries("interceptors", plan)

        async def dispatch(index: int) -> PipelineResult:
            if index == len(entries):
                return PipelineResult.from_value(await terminal())
            called = False

            async def next_once() -> PipelineResult:
                nonlocal called
                if called:
                    raise PipelineStateError(
                        "stream interceptor next callback was called twice"
                    )
                called = True
                return await dispatch(index + 1)

            binding, ref, fallback = entries[index]
            interceptor = cast(
                Interceptor,
                await self._resolve(resolver, binding, ref, fallback),
            )
            result = await interceptor.intercept(context, next_once)
            if not isinstance(result, PipelineResult):
                raise StreamInvocationError(
                    "stream interceptor must return PipelineResult"
                )
            return result

        return await dispatch(0)

    async def _notify_filters(
        self,
        plan: StreamHandlerPlan,
        context: StreamContext,
        resolver: ScopedResolver,
        error: Exception,
    ) -> None:
        for binding, ref, fallback in self._entries("filters", plan):
            try:
                filter_ = cast(
                    ExceptionFilter,
                    await self._resolve(resolver, binding, ref, fallback),
                )
                await filter_.catch(error, context)
            except Exception:
                continue

    async def _call_handler(
        self,
        plan: StreamHandlerPlan,
        resolver: ScopedResolver,
        arguments: dict[str, object],
    ) -> object:
        controller = await self._resolve_ref(resolver, plan.controller_ref)
        result = getattr(controller, plan.method_name)(**arguments)
        if not inspect.isawaitable(result):
            raise StreamInvocationError("compiled stream handler is not async")
        return await result

    def _entries(
        self, kind: str, plan: StreamHandlerPlan
    ) -> tuple[tuple[object, ProviderRef | None, bool], ...]:
        entries: list[tuple[object, ProviderRef | None, bool]] = []
        for pipeline, fallback in (
            (self.global_pipeline, False),
            (plan.controller_pipeline, True),
            (plan.method_pipeline, True),
        ):
            refs = [
                ref
                for ref_kind, ref in pipeline.qualified_provider_refs
                if ref_kind == kind
            ]
            index = 0
            for binding in getattr(pipeline, kind):
                ref = None
                if isinstance(binding, (str, type)):
                    ref = refs[index] if index < len(refs) else None
                    index += 1
                entries.append((binding, ref, fallback))
        return tuple(entries)

    async def _resolve(
        self,
        resolver: ScopedResolver,
        binding: object,
        ref: ProviderRef | None,
        fallback: bool,
    ) -> object:
        if ref is not None:
            return await self._resolve_ref(resolver, ref)
        if isinstance(binding, (str, type)):
            if not fallback:
                raise StreamInvocationError(
                    "global stream pipeline provider was not qualified"
                )
            return await resolver.resolve(binding)
        return binding

    @staticmethod
    async def _resolve_ref(resolver: ScopedResolver, ref: ProviderRef) -> object:
        if not isinstance(resolver, QualifiedScopedResolver):
            raise StreamInvocationError("exact provider resolution is unavailable")
        return await resolver.resolve_ref(ref)


__all__ = ["StreamPipelineExecutor"]
