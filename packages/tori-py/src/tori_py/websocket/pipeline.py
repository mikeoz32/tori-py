"""Framework-owned WebSocket connection pipeline execution."""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol, cast

from tori_py.core.compiler import CompiledGraph, ModuleId, ProviderRef
from tori_py.core.errors import BootstrapError, PipelineStateError
from tori_py.core.options import PipelineOptions
from tori_py.core.pipeline import PipelineBindings
from tori_py.core.protocols import (
    ArgumentMetadata,
    ExceptionFilter,
    Guard,
    Interceptor,
    Middleware,
    Pipe,
    PipelineResult,
)
from tori_py.core.runtime import RequestScope
from tori_py.websocket.context import WebSocketContext
from tori_py.websocket.errors import WebSocketForbidden
from tori_py.websocket.routes import WebSocketPlan


class WebSocketPipelineAdapter(Protocol):
    """Transport policy needed by the WebSocket pipeline."""

    def is_abort_exception(self, error: BaseException) -> bool:
        """Return whether an error must bypass exception filters."""


class WebSocketPipelineExecutor:
    """Resolve qualified providers and execute one connection pipeline."""

    def __init__(
        self,
        graph: CompiledGraph,
        *,
        global_tokens: PipelineOptions,
        transport: WebSocketPipelineAdapter,
    ) -> None:
        self.graph = graph
        self.root = graph.root
        self.transport = transport
        self.global_tokens = global_tokens
        self.global_pipeline = self._qualify_global(global_tokens)

    def configure_global(self, global_tokens: PipelineOptions) -> None:
        self.global_tokens = global_tokens
        self.global_pipeline = self._qualify_global(global_tokens)

    def qualify(self, plans: Sequence[WebSocketPlan]) -> tuple[WebSocketPlan, ...]:
        self.configure_global(self.global_tokens)
        return tuple(
            replace(
                plan,
                gateway_pipeline=self._qualify_pipeline(
                    plan.gateway_pipeline, plan.module_id
                ),
                handler_pipeline=self._qualify_pipeline(
                    plan.handler_pipeline, plan.module_id
                ),
            )
            for plan in plans
        )

    async def run(
        self,
        plan: WebSocketPlan,
        context: WebSocketContext,
        scope: RequestScope,
        *,
        bind_arguments,
    ) -> PipelineResult:
        try:
            return await self._run_middleware(
                plan,
                context,
                scope,
                bind_arguments=bind_arguments,
            )
        except BaseException as error:
            if self.transport.is_abort_exception(error):
                raise
            if not isinstance(error, Exception):
                raise
            handled = await self._handle_exception(error, plan, context, scope)
            if handled is None:
                raise
            return handled

    async def _run_middleware(
        self,
        plan: WebSocketPlan,
        context: WebSocketContext,
        scope: RequestScope,
        *,
        bind_arguments,
    ) -> PipelineResult:
        middleware = [
            cast(Middleware, instance)
            for bindings in (
                self.global_pipeline.middleware,
                plan.gateway_pipeline.middleware,
                plan.handler_pipeline.middleware,
            )
            for instance in await self._resolve_pipeline(bindings, scope)
        ]

        async def terminal() -> PipelineResult:
            await self._run_guards(plan, context, scope)
            arguments = await bind_arguments()
            await self._run_pipes(plan, scope, arguments)
            return await self._run_interceptors(
                plan,
                context,
                scope,
                lambda: _handler_result(plan, arguments),
            )

        async def dispatch(index: int) -> PipelineResult:
            if index == len(middleware):
                return await terminal()
            called = False

            async def next_once() -> PipelineResult:
                nonlocal called
                if called:
                    raise PipelineStateError("pipeline next callback was called twice")
                called = True
                return await dispatch(index + 1)

            return _normalize(await middleware[index].handle(context, next_once))

        return await dispatch(0)

    async def _run_guards(
        self,
        plan: WebSocketPlan,
        context: WebSocketContext,
        scope: RequestScope,
    ) -> None:
        guards = [
            cast(Guard, instance)
            for bindings in (
                self.global_pipeline.guards,
                plan.gateway_pipeline.guards,
                plan.handler_pipeline.guards,
            )
            for instance in await self._resolve_pipeline(bindings, scope)
        ]
        for guard in guards:
            if not await guard.can_activate(context):
                raise WebSocketForbidden("WebSocket connection was denied")

    async def _run_pipes(
        self,
        plan: WebSocketPlan,
        scope: RequestScope,
        arguments: dict[str, object],
    ) -> None:
        pipes = [
            cast(Pipe, instance)
            for bindings in (
                self.global_pipeline.pipes,
                plan.gateway_pipeline.pipes,
                plan.handler_pipeline.pipes,
            )
            for instance in await self._resolve_pipeline(bindings, scope)
        ]
        for parameter in plan.parameters:
            if parameter.kind in {"socket", "context", "inject"}:
                continue
            metadata = ArgumentMetadata(
                parameter_name=parameter.name,
                binding_kind=parameter.kind,
                source_name=parameter.source,
                annotation=parameter.annotation,
                route_id=plan.route_id,
                module_id=_module_label(plan.module_id),
            )
            for pipe in pipes:
                arguments[parameter.name] = await pipe.transform(
                    arguments[parameter.name], metadata
                )

    async def _run_interceptors(
        self,
        plan: WebSocketPlan,
        context: WebSocketContext,
        scope: RequestScope,
        terminal,
    ) -> PipelineResult:
        interceptors = [
            cast(Interceptor, instance)
            for bindings in (
                self.global_pipeline.interceptors,
                plan.gateway_pipeline.interceptors,
                plan.handler_pipeline.interceptors,
            )
            for instance in await self._resolve_pipeline(bindings, scope)
        ]

        async def dispatch(index: int) -> PipelineResult:
            if index == len(interceptors):
                return await terminal()
            called = False

            async def next_once() -> PipelineResult:
                nonlocal called
                if called:
                    raise PipelineStateError("pipeline next callback was called twice")
                called = True
                return await dispatch(index + 1)

            return _normalize(await interceptors[index].intercept(context, next_once))

        return await dispatch(0)

    async def _handle_exception(
        self,
        error: Exception,
        plan: WebSocketPlan,
        context: WebSocketContext,
        scope: RequestScope,
    ) -> PipelineResult | None:
        for bindings in (
            plan.handler_pipeline.filters,
            plan.gateway_pipeline.filters,
            self.global_pipeline.filters,
        ):
            for binding in bindings:
                try:
                    filter_instance = cast(
                        ExceptionFilter,
                        await scope.resolve_ref(binding)
                        if isinstance(binding, ProviderRef)
                        else binding,
                    )
                    result = await filter_instance.catch(error, context)
                    if not isinstance(result, PipelineResult):
                        raise TypeError("exception filter must return PipelineResult")
                    return result
                except BaseException as filter_error:
                    if self.transport.is_abort_exception(filter_error):
                        raise
                    if not isinstance(filter_error, Exception):
                        raise
        return None

    async def _resolve_pipeline(
        self,
        bindings: Sequence[object],
        scope: RequestScope,
    ) -> list[object]:
        return [
            await scope.resolve_ref(binding)
            if isinstance(binding, ProviderRef)
            else binding
            for binding in bindings
        ]

    def _qualify_global(self, options: PipelineOptions) -> PipelineBindings:
        return self._qualify_bindings(
            options.middleware,
            options.guards,
            options.pipes,
            options.interceptors,
            options.filters,
            self.root,
        )

    def _qualify_pipeline(
        self,
        pipeline: PipelineBindings,
        module_id: ModuleId,
    ) -> PipelineBindings:
        return self._qualify_bindings(
            pipeline.middleware,
            pipeline.guards,
            pipeline.pipes,
            pipeline.interceptors,
            pipeline.filters,
            module_id,
        )

    def _qualify_bindings(
        self,
        middleware: Sequence[object],
        guards: Sequence[object],
        pipes: Sequence[object],
        interceptors: Sequence[object],
        filters: Sequence[object],
        module_id: ModuleId,
    ) -> PipelineBindings:
        return PipelineBindings(
            middleware=self._qualify_kind(middleware, module_id, "middleware"),
            guards=self._qualify_kind(guards, module_id, "guards"),
            pipes=self._qualify_kind(pipes, module_id, "pipes"),
            interceptors=self._qualify_kind(interceptors, module_id, "interceptors"),
            filters=self._qualify_kind(filters, module_id, "filters"),
        )

    def _qualify_kind(
        self,
        bindings: Sequence[object],
        module_id: ModuleId,
        kind: str,
    ) -> tuple[object, ...]:
        qualified: list[object] = []
        for binding in bindings:
            if not isinstance(binding, str | type):
                qualified.append(binding)
                continue
            ref = self.graph.visibility.get((module_id, binding))
            if ref is None:
                raise BootstrapError(
                    "pipeline provider is not visible from its owning module",
                    code="provider.unresolved",
                    details={"kind": kind, "token": repr(binding)},
                )
            qualified.append(ref)
        return tuple(qualified)


def _normalize(value: object) -> PipelineResult:
    if isinstance(value, PipelineResult):
        return value
    return PipelineResult.from_value(value)


async def _handler_result(
    plan: WebSocketPlan,
    arguments: dict[str, object],
) -> PipelineResult:
    result = plan.handler(**arguments)
    if inspect.isawaitable(result):
        result = await result
    return PipelineResult.from_value(result)


def _module_label(module_id: ModuleId) -> str:
    label = module_id.module.__qualname__
    return label if module_id.key is None else f"{label}[{module_id.key}]"


__all__ = ["WebSocketPipelineAdapter", "WebSocketPipelineExecutor"]
