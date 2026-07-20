"""N5 controller pipeline execution and optional msgspec validation."""

from __future__ import annotations

import logging
import types
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Union, cast, get_args, get_origin

import msgspec
from starlette.requests import ClientDisconnect
from starlette.responses import Response

from nestpy.core.compiler import CompiledGraph, ModuleId, ProviderRef
from nestpy.core.errors import BootstrapError, PipelineStateError
from nestpy.core.metadata import get_pipeline_metadata, get_route_metadata
from nestpy.core.modules import ModuleSpec
from nestpy.core.options import StarletteOptions
from nestpy.core.protocols import (
    ArgumentMetadata,
    ExceptionFilter,
    Guard,
    Interceptor,
    Middleware,
    Pipe,
    PipelineResult,
)
from nestpy.core.providers import ClassProvider
from nestpy.starlette.context import RequestContext, current_request_scope
from nestpy.starlette.errors import HttpException, problem_response

if TYPE_CHECKING:
    from nestpy.starlette.routes import RoutePlan

logger = logging.getLogger("nestpy.starlette.pipeline")


type AsyncStep = Callable[[], Awaitable[PipelineResult]]

_ENHANCER_METHODS = {
    "guards": "can_activate",
    "pipes": "transform",
    "interceptors": "intercept",
    "filters": "catch",
}


def pipeline_class_provider_fallbacks(
    spec: ModuleSpec,
    *,
    is_root: bool,
    global_bindings: StarletteOptions,
) -> tuple[ClassProvider, ...]:
    """Return enhancer classes that can back unresolved pipeline registrations."""

    bindings: list[tuple[str, object]] = []
    for controller in spec.controllers:
        route_handlers = tuple(
            handler
            for handler in controller.__dict__.values()
            if get_route_metadata(handler) is not None
        )
        if not route_handlers:
            continue
        for kind in _ENHANCER_METHODS:
            bindings.extend(
                (kind, binding) for binding in get_pipeline_metadata(controller, kind)
            )
        for handler in route_handlers:
            for kind in _ENHANCER_METHODS:
                bindings.extend(
                    (kind, binding) for binding in get_pipeline_metadata(handler, kind)
                )
    if is_root:
        for kind in _ENHANCER_METHODS:
            bindings.extend(
                (kind, binding) for binding in getattr(global_bindings, kind)
            )

    providers: list[ClassProvider] = []
    collected: set[type[object]] = set()
    for kind, binding in bindings:
        if (
            isinstance(binding, type)
            and callable(getattr(binding, _ENHANCER_METHODS[kind], None))
            and binding not in collected
        ):
            providers.append(ClassProvider(binding, binding))
            collected.add(binding)
    return tuple(providers)


class PipelineExecutor:
    """Resolve qualified pipeline providers and execute one route request."""

    def __init__(
        self,
        graph: CompiledGraph,
        *,
        global_tokens: StarletteOptions,
    ) -> None:
        self.graph = graph
        self.root = graph.root
        self.global_tokens = global_tokens
        self.global_pipeline = self._qualify_bindings(
            global_tokens.middleware,
            global_tokens.guards,
            global_tokens.pipes,
            global_tokens.interceptors,
            global_tokens.filters,
            self.root,
        )

    def qualify(self, plans: Sequence[RoutePlan]) -> tuple[RoutePlan, ...]:
        global_pipeline = self._qualify_bindings(
            self.global_tokens.middleware,
            self.global_tokens.guards,
            self.global_tokens.pipes,
            self.global_tokens.interceptors,
            self.global_tokens.filters,
            self.root,
        )
        self.global_pipeline = global_pipeline
        qualified: list[RoutePlan] = []
        for plan in plans:
            qualified.append(
                replace(
                    plan,
                    controller_pipeline=self._qualify_pipeline(
                        plan.controller_pipeline,
                        plan.module_id,
                    ),
                    route_pipeline=self._qualify_pipeline(
                        plan.route_pipeline,
                        plan.module_id,
                    ),
                )
            )
        return tuple(qualified)

    async def run(
        self,
        plan: RoutePlan,
        context: RequestContext,
        *,
        bind_arguments: Callable[[], Awaitable[dict[str, object]]],
        invoke_handler: Callable[[dict[str, object]], Awaitable[object]],
        encode_result: Callable[[object], Awaitable[Response]],
    ) -> Response:
        try:
            result = await self._run_middleware(
                plan,
                context,
                bind_arguments=bind_arguments,
                invoke_handler=invoke_handler,
            )
        except ClientDisconnect:
            raise
        except Exception as error:
            return await self._render_exception(error, plan, context, encode_result)
        try:
            return await encode_result(result)
        except ClientDisconnect:
            raise
        except Exception as error:
            return await self._render_exception(error, plan, context, encode_result)

    async def handle_routing_error(
        self,
        error: Exception,
        context: RequestContext,
        *,
        encode_result: Callable[[object], Awaitable[Response]],
    ) -> Response:
        try:
            result = await self._handle_exception(error, None, context)
            return await encode_result(result)
        except ClientDisconnect:
            raise
        except Exception as render_error:
            logger.error(
                "Routing error response could not be rendered",
                extra={"request_id": context.request_id},
                exc_info=(
                    type(render_error),
                    render_error,
                    render_error.__traceback__,
                ),
            )
            return problem_response(
                500,
                "Internal server error.",
                request=context.request,
            )

    async def _run_middleware(
        self,
        plan: RoutePlan,
        context: RequestContext,
        *,
        bind_arguments: Callable[[], Awaitable[dict[str, object]]],
        invoke_handler: Callable[[dict[str, object]], Awaitable[object]],
    ) -> PipelineResult:
        middleware = [
            cast(Middleware, instance)
            for instance in await self._resolve_pipeline(
                self.global_pipeline.middleware,
                self.root,
            )
        ]
        middleware += [
            cast(Middleware, instance)
            for instance in await self._resolve_pipeline(
                plan.controller_pipeline.middleware,
                plan.module_id,
            )
        ]
        middleware += [
            cast(Middleware, instance)
            for instance in await self._resolve_pipeline(
                plan.route_pipeline.middleware,
                plan.module_id,
            )
        ]

        async def terminal() -> PipelineResult:
            await self._run_guards(plan, context)
            arguments = await bind_arguments()
            await self._run_pipes(plan, context, arguments)
            return await self._run_interceptors(
                plan,
                context,
                lambda: _handler_result(invoke_handler, arguments),
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
            return _as_pipeline_result(result)

        return await dispatch(0)

    async def _run_guards(self, plan: RoutePlan, context: RequestContext) -> None:
        guards = [
            cast(Guard, instance)
            for instance in await self._resolve_pipeline(
                self.global_pipeline.guards,
                self.root,
            )
        ]
        guards += [
            cast(Guard, instance)
            for instance in await self._resolve_pipeline(
                plan.controller_pipeline.guards,
                plan.module_id,
            )
        ]
        guards += [
            cast(Guard, instance)
            for instance in await self._resolve_pipeline(
                plan.route_pipeline.guards,
                plan.module_id,
            )
        ]
        for guard in guards:
            if not await guard.can_activate(context):
                raise HttpException(403, "Forbidden.")

    async def _run_pipes(
        self,
        plan: RoutePlan,
        context: RequestContext,
        arguments: dict[str, object],
    ) -> None:
        pipes = [
            cast(Pipe, instance)
            for instance in await self._resolve_pipeline(
                self.global_pipeline.pipes,
                self.root,
            )
        ]
        controller_pipes = [
            cast(Pipe, instance)
            for instance in await self._resolve_pipeline(
                plan.controller_pipeline.pipes,
                plan.module_id,
            )
        ]
        route_pipes = [
            cast(Pipe, instance)
            for instance in await self._resolve_pipeline(
                plan.route_pipeline.pipes,
                plan.module_id,
            )
        ]
        all_pipes = pipes + controller_pipes + route_pipes
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
                    arguments[parameter.name],
                    metadata,
                )

    async def _run_interceptors(
        self,
        plan: RoutePlan,
        context: RequestContext,
        terminal: AsyncStep,
    ) -> PipelineResult:
        interceptors = [
            cast(Interceptor, instance)
            for instance in await self._resolve_pipeline(
                self.global_pipeline.interceptors,
                self.root,
            )
        ]
        interceptors += [
            cast(Interceptor, instance)
            for instance in await self._resolve_pipeline(
                plan.controller_pipeline.interceptors,
                plan.module_id,
            )
        ]
        interceptors += [
            cast(Interceptor, instance)
            for instance in await self._resolve_pipeline(
                plan.route_pipeline.interceptors,
                plan.module_id,
            )
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
            return _as_pipeline_result(result)

        return await dispatch(0)

    async def _handle_exception(
        self,
        error: Exception,
        plan: RoutePlan | None,
        context: RequestContext,
    ) -> PipelineResult:
        if isinstance(error, ClientDisconnect):
            raise error
        try:
            filters: list[ExceptionFilter] = []
            if plan is not None:
                filters.extend(
                    cast(ExceptionFilter, filter_instance)
                    for filter_instance in await self._resolve_pipeline(
                        plan.route_pipeline.filters,
                        plan.module_id,
                    )
                )
                filters.extend(
                    cast(ExceptionFilter, filter_instance)
                    for filter_instance in await self._resolve_pipeline(
                        plan.controller_pipeline.filters,
                        plan.module_id,
                    )
                )
            filters.extend(
                cast(ExceptionFilter, filter_instance)
                for filter_instance in await self._resolve_pipeline(
                    self.global_pipeline.filters,
                    self.root,
                )
            )
        except Exception:
            logger.exception("Exception filters could not be resolved")
            filters = []
        for filter_instance in filters:
            try:
                result = await filter_instance.catch(error, context)
                if isinstance(result, PipelineResult):
                    return result
                if isinstance(result, Response):
                    return PipelineResult.from_response(result)
                raise TypeError("exception filter must return PipelineResult")
            except Exception:
                logger.exception(
                    "Exception filter failed", extra={"request_id": context.request_id}
                )
        if isinstance(error, HttpException):
            response = problem_response(
                error.status_code,
                error.detail,
                request=context.request,
                title=error.title,
                headers=error.headers,
                errors=error.errors,
            )
        else:
            logger.error(
                "Unhandled application exception",
                extra={"request_id": context.request_id},
                exc_info=(type(error), error, error.__traceback__),
            )
            response = problem_response(
                500,
                "Internal server error.",
                request=context.request,
            )
        return PipelineResult.from_response(response)

    async def _render_exception(
        self,
        error: Exception,
        plan: RoutePlan,
        context: RequestContext,
        encode_result: Callable[[object], Awaitable[Response]],
    ) -> Response:
        try:
            result = await self._handle_exception(error, plan, context)
            return await encode_result(result)
        except Exception as render_error:
            logger.error(
                "Exception response could not be rendered",
                extra={"request_id": context.request_id},
                exc_info=(
                    type(render_error),
                    render_error,
                    render_error.__traceback__,
                ),
            )
            return problem_response(
                500,
                "Internal server error.",
                request=context.request,
            )

    async def _resolve_pipeline(
        self,
        bindings: Sequence[object],
        module_id: ModuleId,
    ) -> list[object]:
        request_scope = current_request_scope()
        if request_scope is None:
            raise BootstrapError(
                "pipeline resolution requires a request scope",
                code="pipeline.invalid_state",
            )
        del module_id
        return [
            await request_scope.resolve_ref(binding)
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
    ):
        from nestpy.starlette.routes import PipelineBindings

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

    def _qualify_pipeline(self, pipeline, module_id: ModuleId):
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


class MsgspecValidationPipe:
    """Opt-in raw HTTP value conversion through msgspec."""

    async def transform(self, value: object, metadata: ArgumentMetadata) -> object:
        try:
            return _convert_raw(value, metadata.annotation)
        except (TypeError, ValueError, msgspec.ValidationError) as error:
            raise HttpException(
                400,
                "Validation failed.",
                errors={
                    "parameter": metadata.parameter_name,
                    "source": metadata.binding_kind,
                    "message": str(error),
                },
            ) from error


async def _handler_result(
    invoke_handler: Callable[[dict[str, object]], Awaitable[object]],
    arguments: dict[str, object],
) -> PipelineResult:
    return PipelineResult.from_value(await invoke_handler(arguments))


def _as_pipeline_result(result: object) -> PipelineResult:
    if isinstance(result, PipelineResult):
        return result
    if isinstance(result, Response):
        return PipelineResult.from_response(result)
    return PipelineResult.from_value(result)


def _module_label(module_id: ModuleId) -> str:
    label = module_id.module.__qualname__
    return label if module_id.key is None else f"{label}[{module_id.key}]"


def _convert_raw(value: object, target: object) -> object:
    try:
        return msgspec.convert(value, type=target)
    except TypeError, ValueError, msgspec.ValidationError:
        pass
    origin = get_origin(target)
    args = get_args(target)
    if origin in {list, tuple, set, frozenset} and isinstance(value, list):
        item_target = args[0] if args else object
        converted = [_convert_raw(item, item_target) for item in value]
        return msgspec.convert(converted, type=target)
    if origin in {types.UnionType, Union}:
        for option in args:
            if option is type(None):
                continue
            try:
                return _convert_raw(value, option)
            except TypeError, ValueError, msgspec.ValidationError:
                continue
    if isinstance(value, str):
        if target is bool:
            normalized = value.casefold()
            if normalized in {"true", "1"}:
                return True
            if normalized in {"false", "0"}:
                return False
        if target in {int, float}:
            if target is int:
                return int(value)
            return float(value)
    return msgspec.convert(value, type=target)


__all__ = ["MsgspecValidationPipe", "PipelineExecutor"]
