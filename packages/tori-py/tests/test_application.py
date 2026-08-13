import pytest
from tori_py import (
    ApplicationAdapter,
    ApplicationBinder,
    ApplicationRuntime,
    ApplicationStateError,
    BootstrapError,
    CompiledGraph,
    ModuleId,
    ModuleSpec,
    NestApplication,
    PipelineOptions,
    PipelineResult,
    ProviderDeclaration,
    module,
)
from tori_py.core.runtime import ApplicationState
from tori_py.starlette import StarletteAdapter, asgi


@pytest.mark.asyncio
async def test_application_without_adapter_is_driver_neutral() -> None:
    @module()
    class Root:
        pass

    application = await NestApplication.create(Root)
    assert application.state is ApplicationState.COMPILED
    with pytest.raises(ApplicationStateError, match="does not use StarletteAdapter"):
        application.get_adapter(StarletteAdapter)
    await application.start()
    assert application.state is ApplicationState.STARTED
    await application.shutdown()
    assert application.state is ApplicationState.STOPPED


@pytest.mark.asyncio
async def test_global_pipeline_is_validated_without_transport_adapter() -> None:
    @module()
    class Root:
        pass

    with pytest.raises(BootstrapError, match="pipeline provider"):
        await NestApplication.create(
            Root,
            pipeline=PipelineOptions(guards=("missing",)),
        )


@pytest.mark.asyncio
async def test_global_enhancer_methods_configure_adapter_before_start() -> None:
    configured: list[PipelineOptions] = []
    lifecycle_events: list[str] = []

    class GlobalGuard:
        async def can_activate(self, context) -> bool:
            return True

    class GlobalPipe:
        async def transform(self, value, metadata):
            return value

        async def on_module_init(self) -> None:
            lifecycle_events.append("init")

        async def on_module_destroy(self) -> None:
            lifecycle_events.append("destroy")

    class GlobalInterceptor:
        async def intercept(self, context, next):
            return await next()

    class GlobalFilter:
        async def catch(self, error, context):
            return PipelineResult.from_value("handled")

    class Binder:
        async def bind(self, runtime: ApplicationRuntime) -> None:
            pass

        async def close(self) -> None:
            pass

    class Adapter:
        def collect_fallback_providers(
            self,
            module_id: ModuleId,
            spec: ModuleSpec,
            is_root: bool,
            pipeline: PipelineOptions,
        ) -> tuple[ProviderDeclaration, ...]:
            return ()

        def create_binder(
            self,
            graph: CompiledGraph,
            pipeline: PipelineOptions,
        ) -> ApplicationBinder:
            configured.append(pipeline)
            return Binder()

        def configure_pipeline(self, pipeline: PipelineOptions) -> None:
            configured.append(pipeline)

    @module()
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=Adapter())
    guard = GlobalGuard()
    pipe = GlobalPipe()
    interceptor = GlobalInterceptor()
    filter_ = GlobalFilter()

    assert application.use_global_guard(guard) is application
    assert application.use_global_pipe(pipe) is application
    assert application.use_global_interceptor(interceptor) is application
    assert application.use_global_filter(filter_) is application
    assert configured[-1] == PipelineOptions(
        guards=(guard,),
        pipes=(pipe,),
        interceptors=(interceptor,),
        filters=(filter_,),
    )

    with pytest.raises(BootstrapError, match="not visible"):
        application.use_global_guard(GlobalGuard)

    await application.start()
    with pytest.raises(ApplicationStateError, match="before application startup"):
        application.use_global_pipe(pipe)
    await application.shutdown()
    assert lifecycle_events == []


@pytest.mark.asyncio
async def test_starlette_adapter_is_owned_by_one_application() -> None:
    @module()
    class Root:
        pass

    adapter = StarletteAdapter()
    assert ApplicationAdapter in StarletteAdapter.__bases__
    application = await NestApplication.create(Root, adapter=adapter)
    assert application.get_adapter(StarletteAdapter) is adapter
    with pytest.raises(ApplicationStateError, match="cannot be reused"):
        await NestApplication.create(Root, adapter=adapter)


@pytest.mark.asyncio
async def test_falsey_adapter_is_not_replaced_by_noop() -> None:
    class FalseyStarletteAdapter(StarletteAdapter):
        def __bool__(self) -> bool:
            return False

    @module()
    class Root:
        pass

    adapter = FalseyStarletteAdapter()
    application = await NestApplication.create(Root, adapter=adapter)
    assert application.get_adapter(FalseyStarletteAdapter) is adapter


@pytest.mark.asyncio
async def test_falsey_adapter_binder_receives_lifecycle() -> None:
    events: list[str] = []

    class FalseyBinder:
        def __bool__(self) -> bool:
            return False

        async def bind(self, runtime: ApplicationRuntime) -> None:
            assert isinstance(runtime, ApplicationRuntime)
            events.append("bind")

        async def close(self) -> None:
            events.append("close")

    class Adapter:
        def collect_fallback_providers(
            self,
            module_id: ModuleId,
            spec: ModuleSpec,
            is_root: bool,
            pipeline: PipelineOptions,
        ) -> tuple[ProviderDeclaration, ...]:
            return ()

        def create_binder(
            self,
            graph: CompiledGraph,
            pipeline: PipelineOptions,
        ) -> ApplicationBinder:
            return FalseyBinder()

        def configure_pipeline(self, pipeline: PipelineOptions) -> None:
            pass

    @module()
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=Adapter())
    await application.start()
    await application.shutdown()
    assert events == ["bind", "close"]


@pytest.mark.asyncio
async def test_asgi_wrapper_rejects_application_without_starlette_adapter() -> None:
    @module()
    class Root:
        pass

    async def factory() -> NestApplication:
        return await NestApplication.create(Root)

    application = asgi(factory)
    messages: list[dict[str, object]] = []

    async def receive() -> dict[str, str]:
        return {"type": "lifespan.startup"}

    async def send(message) -> None:
        messages.append(dict(message))

    await application({"type": "lifespan"}, receive, send)
    assert messages[0]["type"] == "lifespan.startup.failed"
    assert "StarletteAdapter" in str(messages[0]["message"])
