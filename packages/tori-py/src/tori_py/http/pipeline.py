"""Framework-owned HTTP pipeline execution independent of a transport."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Sequence
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
from tori_py.http.context import HttpContext
from tori_py.http.errors import HttpException
from tori_py.http.routes import RoutePlan

logger = logging.getLogger("tori_py.http.pipeline")

type AsyncStep = Callable[[], Awaitable[PipelineResult]]


class HttpPipelineAdapter(Protocol):
    """Transport operations needed by framework-owned pipeline execution."""

    def is_abort_exception(self, error: BaseException) -> bool:
        """Return whether an error must bypass filters and rendering."""

    def normalize_result(self, value: object) -> PipelineResult:
        """Normalize values and native responses returned by pipeline stages."""

    def native_response_result(self, value: object) -> PipelineResult | None:
        """Return an opaque response result for a native response value."""

    def render_exception(
        self,
        error: Exception,
        context: HttpContext,
    ) -> PipelineResult:
        """Render the framework default HTTP error response."""

    def render_emergency(self, context: HttpContext) -> object:
        """Return a final response when normal error rendering fails."""


class PipelineExecutor:
    """Resolve qualified providers and execute one framework HTTP pipeline."""

    def __init__(
        self,
        graph: CompiledGraph,
        *,
        global_tokens: PipelineOptions,
        transport: HttpPipelineAdapter,
    ) -> None:
        self.graph = graph
        self.root = graph.root
        self.transport = transport
        self.global_tokens = global_tokens
        self.global_pipeline = self._qualify_global(global_tokens)

    def configure_global(self, global_tokens: PipelineOptions) -> None:
        """Replace global registrations before transport binding."""

        self.global_tokens = global_tokens
        self.global_pipeline = self._qualify_global(global_tokens)

    def _qualify_global(self, global_tokens: PipelineOptions) -> PipelineBindings:
        return self._qualify_bindings(
            global_tokens.middleware,
            global_tokens.guards,
            global_tokens.pipes,
            global_tokens.interceptors,
            global_tokens.filters,
            self.root,
        )

    def qualify(self, plans: Sequence[RoutePlan]) -> tuple[RoutePlan, ...]:
        self.configure_global(self.global_tokens)
        return tuple(
            replace(
                plan,
                controller_pipeline=self._qualify_pipeline(
                    plan.controller_pipeline, plan.module_id
                ),
                route_pipeline=self._qualify_pipeline(
                    plan.route_pipeline, plan.module_id
                ),
            )
            for plan in plans
        )

    async def run(
        self,
        plan: RoutePlan,
        context: HttpContext,
        scope: RequestScope,
        *,
        bind_arguments: Callable[[], Awaitable[dict[str, object]]],
        encode_result: Callable[[object], Awaitable[object]],
    ) -> object:
        try:
            result = await self._run_middleware(
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
            return await self._render_exception(
                error, plan, context, scope, encode_result
            )
        try:
            return await encode_result(result)
        except BaseException as error:
            if self.transport.is_abort_exception(error):
                raise
            if not isinstance(error, Exception):
                raise
            return await self._render_exception(
                error, plan, context, scope, encode_result
            )

    async def handle_routing_error(
        self,
        error: Exception,
        context: HttpContext,
        scope: RequestScope,
        *,
        encode_result: Callable[[object], Awaitable[object]],
    ) -> object:
        if self.transport.is_abort_exception(error):
            raise error
        try:
            result = await self._handle_exception(error, None, context, scope)
            return await encode_result(result)
        except BaseException as render_error:
            if self.transport.is_abort_exception(render_error):
                raise
            if not isinstance(render_error, Exception):
                raise
            logger.error(
                "Routing error response could not be rendered",
                extra={"request_id": context.request_id},
                exc_info=(
                    type(render_error),
                    render_error,
                    render_error.__traceback__,
                ),
            )
            return self.transport.render_emergency(context)

    async def _run_middleware(
        self,
        plan: RoutePlan,
        context: HttpContext,
        scope: RequestScope,
        *,
        bind_arguments: Callable[[], Awaitable[dict[str, object]]],
    ) -> PipelineResult:
        middleware = [
            cast(Middleware, instance)
            for instance in await self._resolve_pipeline(
                self.global_pipeline.middleware, scope
            )
        ]
        middleware += [
            cast(Middleware, instance)
            for instance in await self._resolve_pipeline(
                plan.controller_pipeline.middleware, scope
            )
        ]
        middleware += [
            cast(Middleware, instance)
            for instance in await self._resolve_pipeline(
                plan.route_pipeline.middleware, scope
            )
        ]

        async def terminal() -> PipelineResult:
            await self._run_guards(plan, context, scope)
            arguments = await bind_arguments()
            await self._run_pipes(plan, context, scope, arguments)
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

            result = await middleware[index].handle(context, next_once)
            return self.transport.normalize_result(result)

        return await dispatch(0)

    async def _run_guards(
        self,
        plan: RoutePlan,
        context: HttpContext,
        scope: RequestScope,
    ) -> None:
        guards = [
            cast(Guard, instance)
            for bindings in (
                self.global_pipeline.guards,
                plan.controller_pipeline.guards,
                plan.route_pipeline.guards,
            )
            for instance in await self._resolve_pipeline(bindings, scope)
        ]
        for guard in guards:
            if not await guard.can_activate(context):
                raise HttpException(403, "Forbidden.")

    async def _run_pipes(
        self,
        plan: RoutePlan,
        context: HttpContext,
        scope: RequestScope,
        arguments: dict[str, object],
    ) -> None:
        del context
        all_pipes = [
            cast(Pipe, instance)
            for bindings in (
                self.global_pipeline.pipes,
                plan.controller_pipeline.pipes,
                plan.route_pipeline.pipes,
            )
            for instance in await self._resolve_pipeline(bindings, scope)
        ]
        for parameter in plan.parameters:
            if parameter.kind in {"context", "inject"}:
                continue
            metadata = ArgumentMetadata(
                parameter_name=parameter.name,
                binding_kind=parameter.kind,
                source_name=parameter.source,
                annotation=parameter.annotation,
                route_id=plan.route_id,
                module_id=_module_label(plan.module_id),
            )
            for pipe in all_pipes:
                arguments[parameter.name] = await pipe.transform(
                    arguments[parameter.name], metadata
                )

    async def _run_interceptors(
        self,
        plan: RoutePlan,
        context: HttpContext,
        scope: RequestScope,
        terminal: AsyncStep,
    ) -> PipelineResult:
        interceptors = [
            cast(Interceptor, instance)
            for bindings in (
                self.global_pipeline.interceptors,
                plan.controller_pipeline.interceptors,
                plan.route_pipeline.interceptors,
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

            result = await interceptors[index].intercept(context, next_once)
            return self.transport.normalize_result(result)

        return await dispatch(0)

    async def _handle_exception(
        self,
        error: Exception,
        plan: RoutePlan | None,
        context: HttpContext,
        scope: RequestScope,
    ) -> PipelineResult:
        if self.transport.is_abort_exception(error):
            raise error
        filter_groups = (
            (plan.route_pipeline.filters, plan.controller_pipeline.filters)
            if plan is not None
            else ()
        ) + (self.global_pipeline.filters,)
        for bindings in filter_groups:
            for binding in bindings:
                try:
                    filter_instance = cast(
                        ExceptionFilter,
                        await scope.resolve_ref(binding)
                        if isinstance(binding, ProviderRef)
                        else binding,
                    )
                except BaseException as resolution_error:
                    if self.transport.is_abort_exception(resolution_error):
                        raise
                    if not isinstance(resolution_error, Exception):
                        raise
                    logger.exception(
                        "Exception filter could not be resolved",
                        extra={"request_id": context.request_id},
                    )
                    continue
                try:
                    result = await filter_instance.catch(error, context)
                    if isinstance(result, PipelineResult):
                        return result
                    native = self.transport.native_response_result(result)
                    if native is not None:
                        return native
                    raise TypeError("exception filter must return PipelineResult")
                except BaseException as filter_error:
                    if self.transport.is_abort_exception(filter_error):
                        raise
                    if not isinstance(filter_error, Exception):
                        raise
                    logger.exception(
                        "Exception filter failed",
                        extra={"request_id": context.request_id},
                    )
        return self.transport.render_exception(error, context)

    async def _render_exception(
        self,
        error: Exception,
        plan: RoutePlan,
        context: HttpContext,
        scope: RequestScope,
        encode_result: Callable[[object], Awaitable[object]],
    ) -> object:
        try:
            result = await self._handle_exception(error, plan, context, scope)
            return await encode_result(result)
        except BaseException as render_error:
            if self.transport.is_abort_exception(render_error):
                raise
            if not isinstance(render_error, Exception):
                raise
            logger.error(
                "Exception response could not be rendered",
                extra={"request_id": context.request_id},
                exc_info=(
                    type(render_error),
                    render_error,
                    render_error.__traceback__,
                ),
            )
            return self.transport.render_emergency(context)

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
            middleware=self._qualify_bindings_for_kind(
                middleware, module_id, "middleware"
            ),
            guards=self._qualify_bindings_for_kind(guards, module_id, "guards"),
            pipes=self._qualify_bindings_for_kind(pipes, module_id, "pipes"),
            interceptors=self._qualify_bindings_for_kind(
                interceptors, module_id, "interceptors"
            ),
            filters=self._qualify_bindings_for_kind(filters, module_id, "filters"),
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

    def _qualify_bindings_for_kind(
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


async def _handler_result(
    plan: RoutePlan,
    arguments: dict[str, object],
) -> PipelineResult:
    result = plan.handler(**arguments)
    if inspect.isawaitable(result):
        result = await result
    return PipelineResult.from_value(result)


def _module_label(module_id: ModuleId) -> str:
    label = module_id.module.__qualname__
    return label if module_id.key is None else f"{label}[{module_id.key}]"


__all__ = ["HttpPipelineAdapter", "PipelineExecutor"]
