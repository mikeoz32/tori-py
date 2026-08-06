"""Driver-neutral public application assembly and lifecycle facade."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Protocol, Self, cast, runtime_checkable

from nestpy.core.compiler import CompiledGraph, ModuleId, compile_graph
from nestpy.core.errors import ApplicationStateError, BootstrapError
from nestpy.core.modules import DeferredModule, ModuleImport, ModuleSpec
from nestpy.core.options import ApplicationOptions, PipelineOptions
from nestpy.core.pipeline import (
    pipeline_class_provider_fallbacks,
    validate_pipeline_options,
)
from nestpy.core.protocols import (
    ExceptionFilter,
    Guard,
    Interceptor,
    Pipe,
    QualifiedScopedResolver,
)
from nestpy.core.providers import ProviderDeclaration, Token
from nestpy.core.runtime import (
    ApplicationKernel,
    ApplicationState,
    DriverBinder,
    RequestScope,
)


@runtime_checkable
class ApplicationRuntime(Protocol):
    """Narrow runtime surface available to an application binder."""

    @property
    def graph(self) -> CompiledGraph:
        """Return the immutable graph owned by this application."""

    def request_scope(self, module_id: ModuleId) -> RequestScope:
        """Create one normal driver-request scope."""

    def resolver(self, module_id: ModuleId) -> QualifiedScopedResolver:
        """Return an application-scope resolver for one module."""


@runtime_checkable
class ApplicationBinder(Protocol):
    """Bind and close one prepared external driver."""

    async def bind(self, runtime: ApplicationRuntime) -> None:
        """Bind after providers and modules initialize."""

    async def close(self) -> None:
        """Close one attempted binding."""


class _NoopApplicationBinder:
    async def bind(self, runtime: ApplicationRuntime) -> None:
        del runtime

    async def close(self) -> None:
        return None


@runtime_checkable
class ApplicationAdapter(Protocol):
    """Extend graph compilation and create one external driver binder."""

    def collect_fallback_providers(
        self,
        module_id: ModuleId,
        spec: ModuleSpec,
        is_root: bool,
        pipeline: PipelineOptions,
    ) -> Iterable[ProviderDeclaration]:
        """Return providers needed only when no explicit provider is visible."""

    def create_binder(
        self,
        graph: CompiledGraph,
        pipeline: PipelineOptions,
    ) -> ApplicationBinder:
        """Create the binder owned by one compiled application."""

    def configure_pipeline(self, pipeline: PipelineOptions) -> None:
        """Apply a pre-start global pipeline configuration snapshot."""


class NoopApplicationAdapter:
    """Adapter for applications that do not expose an external driver."""

    def collect_fallback_providers(
        self,
        module_id: ModuleId,
        spec: ModuleSpec,
        is_root: bool,
        pipeline: PipelineOptions,
    ) -> tuple[ProviderDeclaration, ...]:
        del module_id, spec, is_root, pipeline
        return ()

    def create_binder(
        self,
        graph: CompiledGraph,
        pipeline: PipelineOptions,
    ) -> ApplicationBinder:
        del graph, pipeline
        return _NoopApplicationBinder()

    def configure_pipeline(self, pipeline: PipelineOptions) -> None:
        del pipeline


class NestApplication:
    """Compiled driver-neutral application with explicit lifecycle control."""

    def __init__(
        self,
        kernel: ApplicationKernel,
        adapter: ApplicationAdapter,
        pipeline: PipelineOptions,
    ) -> None:
        self._kernel = kernel
        self._adapter = adapter
        self._pipeline = pipeline

    @classmethod
    async def create(
        cls,
        root: type[object] | DeferredModule,
        *,
        options: ApplicationOptions | None = None,
        pipeline: PipelineOptions | None = None,
        adapter: ApplicationAdapter | None = None,
    ) -> NestApplication:
        return await _create_application(
            root,
            options=options,
            pipeline=pipeline,
            adapter=adapter,
            application_type=cls,
        )

    @property
    def graph(self) -> CompiledGraph:
        return self._kernel.graph

    @property
    def state(self) -> ApplicationState:
        return self._kernel.state

    def get_adapter[T: ApplicationAdapter](self, adapter_type: type[T]) -> T:
        if not isinstance(self._adapter, adapter_type):
            raise ApplicationStateError(
                f"application does not use {adapter_type.__qualname__}"
            )
        return self._adapter

    def use_global_guard(self, guard: Token | Guard) -> Self:
        """Append one visible provider or external global guard before startup."""

        return self._use_global("guards", guard)

    def use_global_pipe(self, pipe: Token | Pipe) -> Self:
        """Append one visible provider or external global pipe before startup."""

        return self._use_global("pipes", pipe)

    def use_global_interceptor(self, interceptor: Token | Interceptor) -> Self:
        """Append one visible provider or external interceptor before startup."""

        return self._use_global("interceptors", interceptor)

    def use_global_filter(self, filter_: Token | ExceptionFilter) -> Self:
        """Append one visible provider or external global filter before startup."""

        return self._use_global("filters", filter_)

    def _use_global(self, kind: str, enhancer: object) -> Self:
        if self.state is not ApplicationState.COMPILED:
            raise ApplicationStateError(
                "global pipeline can only be configured before application startup"
            )
        values = (*getattr(self._pipeline, kind), enhancer)
        pipeline = replace(self._pipeline, **{kind: values})
        validate_pipeline_options(self.graph, pipeline)
        self._adapter.configure_pipeline(pipeline)
        self._pipeline = pipeline
        return self

    async def start(self) -> None:
        await self._kernel.start()

    async def shutdown(self) -> None:
        await self._kernel.shutdown()


async def _create_application(
    root: type[object] | DeferredModule,
    *,
    options: ApplicationOptions | None = None,
    pipeline: PipelineOptions | None = None,
    adapter: ApplicationAdapter | None = None,
    import_resolver: Callable[[ModuleImport], ModuleImport] | None = None,
    spec_transformer: Callable[[ModuleId, ModuleSpec], ModuleSpec] | None = None,
    graph_validator: Callable[[CompiledGraph], None] | None = None,
    application_type: type[NestApplication] = NestApplication,
) -> NestApplication:
    selected_adapter = NoopApplicationAdapter() if adapter is None else adapter
    if not isinstance(selected_adapter, ApplicationAdapter):
        raise BootstrapError(
            "adapter does not implement ApplicationAdapter",
            code="application.invalid_options",
        )
    pipeline_options = PipelineOptions() if pipeline is None else pipeline

    def collect_fallback_providers(
        module_id: ModuleId,
        spec: ModuleSpec,
        is_root: bool,
    ) -> Iterable[ProviderDeclaration]:
        yield from pipeline_class_provider_fallbacks(
            spec,
            is_root=is_root,
            global_bindings=pipeline_options,
        )
        yield from selected_adapter.collect_fallback_providers(
            module_id, spec, is_root, pipeline_options
        )

    graph = await compile_graph(
        root,
        import_resolver=import_resolver,
        spec_transformer=spec_transformer,
        fallback_provider_collector=collect_fallback_providers,
    )
    validate_pipeline_options(graph, pipeline_options)
    if graph_validator is not None:
        graph_validator(graph)
    binder = selected_adapter.create_binder(graph, pipeline_options)
    if not isinstance(binder, ApplicationBinder):
        raise BootstrapError(
            "adapter binder does not implement ApplicationBinder",
            code="application.invalid_options",
        )
    kernel = ApplicationKernel(
        graph,
        options=options,
        binder=cast(DriverBinder, binder),
    )
    return application_type(kernel, selected_adapter, pipeline_options)


__all__ = [
    "ApplicationAdapter",
    "ApplicationBinder",
    "ApplicationRuntime",
    "NestApplication",
    "NoopApplicationAdapter",
]
