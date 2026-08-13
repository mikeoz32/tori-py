from typing import Annotated, Any, cast

import pytest
import tori_py
import tori_py.core.compiler as compiler_module
from tori_py import (
    AliasProvider,
    BootstrapError,
    ClassProvider,
    DeferredModule,
    DiscoveryService,
    FactoryProvider,
    Inject,
    ModulesContainer,
    ModuleSpec,
    Reflector,
    Scope,
    ValueProvider,
    WorkScopeFactory,
    compile_graph,
    injectable,
    module,
)


async def compile_root(root: type[object] | DeferredModule):
    return await compile_graph(root)


@pytest.mark.asyncio
async def test_static_imports_reuse_nodes_and_providers_are_not_constructed() -> None:
    constructed = 0

    class Child:
        def __init__(self) -> None:
            nonlocal constructed
            constructed += 1

    @module(providers=[ClassProvider(Child)])
    class ChildModule:
        pass

    @module(imports=[ChildModule, ChildModule])
    class RootModule:
        pass

    graph = await compile_root(RootModule)

    assert tuple(plan.module for plan in graph.modules) == (ChildModule, RootModule)
    assert constructed == 0
    assert len(graph.providers) == 1


@pytest.mark.asyncio
async def test_injectable_class_shorthand_normalizes_to_class_provider() -> None:
    @injectable(scope=Scope.REQUEST, manage=False)
    class Dependency:
        pass

    @injectable(scope=Scope.REQUEST)
    class Consumer:
        def __init__(self, dependency: Dependency) -> None:
            self.dependency = dependency

    @module(providers=[Dependency, Consumer], exports=[Consumer])
    class Root:
        pass

    graph = await compile_root(Root)
    dependency = graph.providers[graph.visibility[(graph.root, Dependency)]]
    consumer = graph.providers[graph.visibility[(graph.root, Consumer)]]

    assert isinstance(dependency.declaration, ClassProvider)
    assert dependency.scope is Scope.REQUEST
    assert dependency.declaration.manage is False
    assert consumer.dependencies[0].provider_ref == dependency.key


@pytest.mark.asyncio
async def test_explicit_class_provider_ignores_injectable_defaults() -> None:
    @injectable(scope=Scope.REQUEST)
    class Service:
        pass

    @module(providers=[ClassProvider(Service, scope=Scope.TRANSIENT)])
    class Root:
        pass

    graph = await compile_root(Root)
    provider = graph.providers[graph.visibility[(graph.root, Service)]]
    assert provider.scope is Scope.TRANSIENT


@pytest.mark.asyncio
async def test_class_shorthand_requires_direct_injectable_metadata() -> None:
    @injectable()
    class Base:
        pass

    class Child(Base):
        pass

    @module(providers=[Child])
    class StaticRoot:
        pass

    with pytest.raises(BootstrapError, match="must be decorated") as static_error:
        await compile_root(StaticRoot)
    assert static_error.value.diagnostic_code == "provider.invalid_declaration"

    class DynamicModule:
        pass

    descriptor = DeferredModule(
        DynamicModule,
        "invalid-provider",
        lambda: ModuleSpec(providers=[Child]),
    )
    with pytest.raises(BootstrapError, match="must be decorated") as dynamic_error:
        await compile_root(descriptor)
    assert dynamic_error.value.diagnostic_code == "provider.invalid_declaration"


@pytest.mark.asyncio
async def test_work_scope_factory_is_an_intrinsic_dependency() -> None:
    class Consumer:
        def __init__(self, scopes: WorkScopeFactory) -> None:
            self.scopes = scopes

    @module(providers=[ClassProvider(Consumer)])
    class Root:
        pass

    graph = await compile_root(Root)
    plan = graph.providers[graph.visibility[(graph.root, Consumer)]]
    assert plan.dependencies[0].token is WorkScopeFactory
    assert plan.dependencies[0].provider_ref is None
    assert (graph.root, WorkScopeFactory) not in graph.visibility


@pytest.mark.asyncio
async def test_discovery_services_are_intrinsic_dependencies() -> None:
    class Consumer:
        def __init__(
            self,
            modules: ModulesContainer,
            discovery: DiscoveryService,
            reflector: Reflector,
        ) -> None:
            self.modules = modules
            self.discovery = discovery
            self.reflector = reflector

    @module(providers=[ClassProvider(Consumer)])
    class Root:
        pass

    graph = await compile_root(Root)
    plan = graph.providers[graph.visibility[(graph.root, Consumer)]]
    assert [dependency.provider_ref for dependency in plan.dependencies] == [
        None,
        None,
        None,
    ]
    assert [dependency.token for dependency in plan.dependencies] == [
        ModulesContainer,
        DiscoveryService,
        Reflector,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    [WorkScopeFactory, ModulesContainer, DiscoveryService, Reflector],
)
@pytest.mark.asyncio
async def test_framework_dependency_tokens_are_reserved(token) -> None:
    @module(providers=[ValueProvider(token, object())])
    class Root:
        pass

    with pytest.raises(BootstrapError) as captured:
        await compile_root(Root)
    assert captured.value.diagnostic_code == "provider.reserved_token"


@pytest.mark.asyncio
async def test_async_dynamic_materializer_is_awaited_once_and_keys_are_isolated() -> (
    None
):
    calls = 0

    class DynamicModule:
        pass

    async def materialize() -> ModuleSpec:
        nonlocal calls
        calls += 1
        return ModuleSpec(providers=[ValueProvider("value", calls)])

    default = DeferredModule(DynamicModule, "default", materialize)
    other = DeferredModule(DynamicModule, "other", materialize)

    @module(imports=[default, default, other])
    class RootModule:
        pass

    graph = await compile_root(RootModule)

    assert calls == 2
    assert [plan.module_id.key for plan in graph.modules] == [
        "default",
        "other",
        None,
    ]


@pytest.mark.asyncio
async def test_dynamic_identity_conflict_fails_before_second_materialization() -> None:
    calls = 0

    class DynamicModule:
        pass

    def first() -> ModuleSpec:
        nonlocal calls
        calls += 1
        return ModuleSpec()

    def second() -> ModuleSpec:
        raise AssertionError("conflicting descriptor was materialized")

    first_descriptor = DeferredModule(DynamicModule, "same", first)
    second_descriptor = DeferredModule(DynamicModule, "same", second)

    @module(imports=[first_descriptor, second_descriptor])
    class RootModule:
        pass

    with pytest.raises(BootstrapError) as error:
        await compile_root(RootModule)

    assert error.value.diagnostic_code == "module.dynamic_conflict"
    assert calls == 1


@pytest.mark.asyncio
async def test_static_dynamic_conflict_and_module_cycle_are_diagnostics() -> None:
    class SharedModule:
        pass

    dynamic = DeferredModule(SharedModule, "configured", lambda: ModuleSpec())

    conflict_root = module(imports=[SharedModule, dynamic])(
        type("ConflictRoot", (), {})
    )

    with pytest.raises(BootstrapError, match="conflicts") as conflict:
        await compile_root(conflict_root)
    assert conflict.value.diagnostic_code == "module.static_dynamic_conflict"

    first_class: type[object] = type("First", (), {})
    second_class: type[object] = type("Second", (), {})
    first_descriptor: DeferredModule
    second_descriptor: DeferredModule

    def materialize_first() -> ModuleSpec:
        return ModuleSpec(imports=[second_descriptor])

    def materialize_second() -> ModuleSpec:
        return ModuleSpec(imports=[first_descriptor])

    first_descriptor = DeferredModule(first_class, "first", materialize_first)
    second_descriptor = DeferredModule(second_class, "second", materialize_second)

    with pytest.raises(BootstrapError) as cycle:
        await compile_root(first_descriptor)
    assert cycle.value.diagnostic_code == "module.cycle"


@pytest.mark.asyncio
async def test_visibility_prefers_local_then_direct_then_global_and_reexports() -> None:
    token = "service"

    @module(providers=[ValueProvider(token, "direct")], exports=[token])
    class DirectModule:
        pass

    @module(providers=[ValueProvider(token, "global")], exports=[token], global_=True)
    class GlobalModule:
        pass

    @module(imports=[GlobalModule])
    class GlobalWrapper:
        pass

    class Consumer:
        def __init__(self, service: Annotated[object, Inject(token)]) -> None:
            self.service = service

    @module(
        imports=[DirectModule, GlobalWrapper],
        providers=[
            ValueProvider(token, "local"),
            ClassProvider(Consumer),
        ],
    )
    class LocalRoot:
        pass

    local_graph = await compile_root(LocalRoot)
    local_consumer = next(
        plan for plan in local_graph.providers.values() if plan.key.token is Consumer
    )
    assert local_consumer.dependencies[0].provider_ref is not None
    assert local_consumer.dependencies[0].provider_ref.module_id.module is LocalRoot

    class DirectConsumer:
        def __init__(self, service: Annotated[object, Inject(token)]) -> None:
            self.service = service

    @module(
        imports=[DirectModule, GlobalWrapper],
        providers=[ClassProvider(DirectConsumer)],
    )
    class DirectRoot:
        pass

    direct_graph = await compile_root(DirectRoot)
    direct_consumer = next(
        plan
        for plan in direct_graph.providers.values()
        if plan.key.token is DirectConsumer
    )
    assert direct_consumer.dependencies[0].provider_ref is not None
    assert direct_consumer.dependencies[0].provider_ref.module_id.module is DirectModule

    class GlobalConsumer:
        def __init__(self, service: Annotated[object, Inject(token)]) -> None:
            self.service = service

    @module(imports=[GlobalWrapper], providers=[ClassProvider(GlobalConsumer)])
    class GlobalRoot:
        pass

    global_graph = await compile_root(GlobalRoot)
    global_consumer = next(
        plan
        for plan in global_graph.providers.values()
        if plan.key.token is GlobalConsumer
    )
    assert global_consumer.dependencies[0].provider_ref is not None
    assert global_consumer.dependencies[0].provider_ref.module_id.module is GlobalModule

    class Reexport:
        pass

    @module(providers=[ValueProvider(Reexport, "reexported")], exports=[Reexport])
    class ExportedModule:
        pass

    @module(imports=[ExportedModule], exports=[Reexport])
    class ReexportingModule:
        pass

    class ReexportConsumer:
        def __init__(self, value: Reexport) -> None:
            self.value = value

    @module(
        imports=[ReexportingModule],
        providers=[ClassProvider(ReexportConsumer)],
    )
    class ReexportRoot:
        pass

    graph = await compile_root(ReexportRoot)
    consumer = next(
        plan for plan in graph.providers.values() if plan.key.token is ReexportConsumer
    )
    assert consumer.dependencies[0].provider_ref is not None
    assert consumer.dependencies[0].provider_ref.module_id.module is ExportedModule


@pytest.mark.asyncio
async def test_direct_and_global_ambiguity_and_private_provider_fail() -> None:
    class Service:
        pass

    class Consumer:
        def __init__(self, service: Service) -> None:
            self.service = service

    @module(providers=[ValueProvider(Service, object())], exports=[Service])
    class First:
        pass

    @module(providers=[ValueProvider(Service, object())], exports=[Service])
    class Second:
        pass

    @module(imports=[First, Second], providers=[ClassProvider(Consumer)])
    class Ambiguous:
        pass

    with pytest.raises(BootstrapError) as direct:
        await compile_root(Ambiguous)
    assert direct.value.diagnostic_code == "provider.ambiguous"

    @module(providers=[ValueProvider(Service, object())], global_=True)
    class Private:
        pass

    @module(imports=[Private], providers=[ClassProvider(Consumer)])
    class Unresolved:
        pass

    with pytest.raises(BootstrapError) as unresolved:
        await compile_root(Unresolved)
    assert unresolved.value.diagnostic_code == "provider.unresolved"


@pytest.mark.asyncio
async def test_dependency_plans_handle_defaults_inject_and_factory_signatures() -> None:
    token = "repository"

    class Repository:
        pass

    class Consumer:
        def __init__(
            self,
            repository: Annotated[Repository, Inject(token)],
            optional: str = "default",
        ) -> None:
            self.repository = repository
            self.optional = optional

    def make_value(repository: Repository) -> str:
        return str(repository)

    @module(
        providers=[
            ValueProvider(token, Repository()),
            ValueProvider(Repository, Repository()),
            ClassProvider(Consumer),
            FactoryProvider("factory", make_value),
        ]
    )
    class Root:
        pass

    graph = await compile_root(Root)
    consumer = graph.providers[
        next(ref for ref in graph.providers if ref.token is Consumer)
    ]
    assert consumer.dependencies[0].token == token
    assert consumer.dependencies[0].provider_ref is not None
    assert consumer.dependencies[1].token is None


@pytest.mark.asyncio
async def test_aliases_canonicalize_and_scope_paths_are_transitive() -> None:
    alias_token = "alias"

    class RequestValue:
        pass

    class TransientValue:
        def __init__(self, value: RequestValue) -> None:
            self.value = value

    class SingletonValue:
        def __init__(self, value: TransientValue) -> None:
            self.value = value

    @module(
        providers=[
            ClassProvider(RequestValue, scope=Scope.REQUEST),
            ClassProvider(TransientValue, scope=Scope.TRANSIENT),
            ClassProvider(SingletonValue),
            AliasProvider(alias_token, RequestValue),
        ]
    )
    class Root:
        pass

    with pytest.raises(BootstrapError) as error:
        await compile_root(Root)
    assert error.value.diagnostic_code == "provider.scope_violation"
    assert "path" in error.value.diagnostic.details


@pytest.mark.asyncio
async def test_provider_and_alias_cycles_are_rejected() -> None:
    class First:
        def __init__(self, second: object) -> None:
            self.second = second

    class Second:
        def __init__(self, first: object) -> None:
            self.first = first

    First.__init__.__annotations__["second"] = Second
    Second.__init__.__annotations__["first"] = First

    @module(providers=[ClassProvider(First), ClassProvider(Second)])
    class Root:
        pass

    with pytest.raises(BootstrapError) as error:
        await compile_root(Root)
    assert error.value.diagnostic_code == "provider.cycle"

    @module(
        providers=[
            ValueProvider("value", 1),
            AliasProvider("first", "second"),
            AliasProvider("second", "first"),
        ]
    )
    class AliasRoot:
        pass

    with pytest.raises(BootstrapError) as alias_error:
        await compile_root(AliasRoot)
    assert alias_error.value.diagnostic_code == "provider.alias_cycle"


@pytest.mark.asyncio
async def test_invalid_signatures_module_constructor_and_controllers_fail() -> None:
    class RequiredModule:
        def __init__(self, value: object) -> None:
            self.value = value

    with pytest.raises(BootstrapError) as module_error:
        await compile_root(RequiredModule)
    assert module_error.value.diagnostic_code == "module.invalid_constructor"

    class Invalid:
        def __init__(self, value) -> None:
            self.value = value

    @module(providers=[ClassProvider(Invalid)])
    class InvalidRoot:
        pass

    with pytest.raises(BootstrapError) as provider_error:
        await compile_root(InvalidRoot)
    assert provider_error.value.diagnostic_code == "provider.invalid_signature"

    class Controller:
        pass

    @module(controllers=[Controller])
    class ControllerRoot:
        pass

    graph = await compile_root(ControllerRoot)
    controller_plan = next(
        plan for plan in graph.providers.values() if plan.key.token is Controller
    )
    assert controller_plan.scope is Scope.SINGLETON


@pytest.mark.asyncio
async def test_compiled_plans_are_immutable_and_do_not_import_starlette() -> None:
    @module(providers=[ValueProvider("value", 1)])
    class Root:
        pass

    graph = await compile_root(Root)

    with pytest.raises(TypeError):
        graph.providers["invalid"] = object()  # type: ignore[index]
    assert all(
        "starlette" not in type(plan.declaration).__module__
        for plan in graph.providers.values()
    )
    assert hasattr(tori_py, "compile_graph")
    assert isinstance(graph, tori_py.CompiledGraph)
    assert isinstance(graph.root, tori_py.ModuleId)
    assert isinstance(graph.modules[0].spec.providers, tuple)
    with pytest.raises(TypeError):
        graph.visibility["invalid"] = object()  # type: ignore[index]


@pytest.mark.asyncio
async def test_deterministic_module_and_provider_order() -> None:
    class First:
        pass

    class Second:
        pass

    @module(providers=[ClassProvider(First)])
    class FirstModule:
        pass

    @module(providers=[ClassProvider(Second)])
    class SecondModule:
        pass

    @module(imports=[SecondModule, FirstModule])
    class Root:
        pass

    graph = await compile_root(Root)
    assert [plan.module for plan in graph.modules] == [
        SecondModule,
        FirstModule,
        Root,
    ]
    assert [ref.token for ref in graph.provider_order] == [Second, First]


@pytest.mark.asyncio
async def test_malformed_materialization_and_duplicate_provider_fail() -> None:
    class Dynamic:
        pass

    def malformed_factory() -> ModuleSpec:
        return cast(ModuleSpec, object())

    malformed = DeferredModule(Dynamic, "bad", malformed_factory)
    with pytest.raises(BootstrapError) as materialization:
        await compile_root(malformed)
    assert materialization.value.diagnostic_code == "module.materialization_error"

    @module(exports=["private"])
    class InvalidExport:
        pass

    with pytest.raises(BootstrapError) as export_error:
        await compile_root(InvalidExport)
    assert export_error.value.diagnostic_code == "module.invalid_export"

    @module(providers=[ValueProvider("duplicate", 1), ValueProvider("duplicate", 2)])
    class Duplicate:
        pass

    with pytest.raises(BootstrapError) as duplicate_error:
        await compile_root(Duplicate)
    assert duplicate_error.value.diagnostic_code == "provider.duplicate"


@pytest.mark.asyncio
async def test_multiple_inject_markers_and_variadic_parameters_fail() -> None:
    class Dependency:
        pass

    class Multiple:
        def __init__(
            self,
            dependency: Annotated[
                Dependency,
                Inject("one"),
                Inject("two"),
            ],
        ) -> None:
            self.dependency = dependency

    @module(providers=[ValueProvider("one", 1), ClassProvider(Multiple)])
    class MultipleRoot:
        pass

    with pytest.raises(BootstrapError) as multiple_error:
        await compile_root(MultipleRoot)
    assert multiple_error.value.diagnostic_code == "provider.invalid_signature"

    class Variadic:
        def __init__(self, *dependencies: Dependency) -> None:
            self.dependencies = dependencies

    @module(providers=[ClassProvider(Variadic)])
    class VariadicRoot:
        pass

    with pytest.raises(BootstrapError) as variadic_error:
        await compile_root(VariadicRoot)
    assert variadic_error.value.diagnostic_code == "provider.invalid_signature"


@pytest.mark.asyncio
async def test_provider_annotations_are_inspected_once_during_compilation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Dependency:
        pass

    class Consumer:
        def __init__(self, dependency: Dependency) -> None:
            self.dependency = dependency

    @module(
        providers=[ValueProvider(Dependency, Dependency()), ClassProvider(Consumer)]
    )
    class Root:
        pass

    calls = 0
    original = compiler_module.get_type_hints

    def counting_get_type_hints(*args: Any, **kwargs: Any) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return cast(dict[str, object], original(*args, **kwargs))

    monkeypatch.setattr(compiler_module, "get_type_hints", counting_get_type_hints)
    await compile_root(Root)
    assert calls == 1


@pytest.mark.asyncio
async def test_global_module_can_reexport_an_imported_token() -> None:
    class Service:
        pass

    @module(providers=[ValueProvider(Service, object())], exports=[Service])
    class Source:
        pass

    @module(imports=[Source], exports=[Service], global_=True)
    class GlobalReexport:
        pass

    @module(imports=[GlobalReexport])
    class Wrapper:
        pass

    class Consumer:
        def __init__(self, service: Service) -> None:
            self.service = service

    @module(imports=[Wrapper], providers=[ClassProvider(Consumer)])
    class Root:
        pass

    graph = await compile_root(Root)
    consumer = next(
        plan for plan in graph.providers.values() if plan.key.token is Consumer
    )
    assert consumer.dependencies[0].provider_ref is not None
    assert consumer.dependencies[0].provider_ref.module_id.module is Source
