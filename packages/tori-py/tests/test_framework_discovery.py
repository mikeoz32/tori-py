from typing import Any, cast

import pytest
from tori_py import (
    AliasProvider,
    BootstrapError,
    ClassProvider,
    DiscoveryService,
    FactoryProvider,
    MetadataDecorator,
    MetadataKey,
    ModuleId,
    ModulesContainer,
    Reflector,
    Scope,
    ScopeError,
    WorkScopeFactory,
    controller,
    metadata,
    module,
)
from tori_py.testing import TestingModule


def test_typed_metadata_supports_direct_inherited_and_instance_lookup() -> None:
    roles: MetadataDecorator[tuple[str, ...]] = Reflector.create_decorator("roles")
    method_label = MetadataKey[str]("method-label")

    @roles(("admin",))
    class Base:
        @metadata(method_label, "run")
        def run(self) -> None:
            return None

    class Child(Base):
        pass

    reflector = Reflector()
    assert reflector.get(roles, Base) == ("admin",)
    assert reflector.get(roles, Child()) == ("admin",)
    assert reflector.get_own(roles, Child) is None
    assert reflector.get(method_label, Child().run) == "run"
    assert roles.KEY is roles.key
    assert Reflector.create_decorator("roles").key != roles.key

    nullable: MetadataDecorator[str | None] = Reflector.create_decorator("nullable")

    @nullable("base")
    class NullableBase:
        pass

    @nullable(None)
    class NullableChild(NullableBase):
        pass

    assert reflector.has(nullable, NullableChild)
    assert reflector.has_own(nullable, NullableChild())
    assert reflector.get(nullable, NullableChild) is None
    assert (
        reflector.get_all_and_override(nullable, [NullableChild, NullableBase]) is None
    )


def test_invalid_or_duplicate_metadata_fails_deterministically() -> None:
    marker: MetadataDecorator[str] = Reflector.create_decorator("marker")

    @marker("first")
    class Target:
        pass

    with pytest.raises(BootstrapError, match="already declared"):
        marker("second")(Target)
    with pytest.raises(BootstrapError, match="class or function"):
        marker("invalid")(object())
    with pytest.raises(BootstrapError, match="non-empty"):
        MetadataKey[object]("")

    plain = type("Plain", (), {})
    invalid_key = cast(Any, object())
    reflector = Reflector()
    for lookup in (
        reflector.get_own,
        reflector.has_own,
        reflector.get,
        reflector.has,
    ):
        with pytest.raises(BootstrapError, match="MetadataKey"):
            lookup(invalid_key, plain)


@pytest.mark.asyncio
async def test_discovery_is_global_read_only_and_does_not_construct_scoped_values() -> (
    None
):
    discoverable: MetadataDecorator[str] = Reflector.create_decorator("discoverable")
    nullable: MetadataDecorator[str | None] = Reflector.create_decorator("nullable")
    managed_marker: MetadataDecorator[str] = Reflector.create_decorator("managed")
    constructions = 0

    @nullable(None)
    @discoverable("private")
    class PrivateService:
        pass

    @managed_marker("resource")
    class ManagedService:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            return None

    class RequestService:
        def __init__(self) -> None:
            nonlocal constructions
            constructions += 1

    def none_factory() -> object:
        return None

    @controller()
    class Controller:
        pass

    @module(
        providers=[
            ClassProvider(PrivateService),
            AliasProvider("private-alias", PrivateService),
            ClassProvider(ManagedService),
            FactoryProvider("none", none_factory),
            ClassProvider(RequestService, scope=Scope.REQUEST),
        ],
        controllers=[Controller],
    )
    class Feature:
        pass

    class Observer:
        def __init__(
            self,
            modules: ModulesContainer,
            discovery: DiscoveryService,
            reflector: Reflector,
        ) -> None:
            self.modules = modules
            self.discovery = discovery
            self.reflector = reflector

    @module(imports=[Feature], providers=[ClassProvider(Observer)])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    observer = await application.resolve(Observer)
    assert isinstance(observer, Observer)
    assert isinstance(observer.modules, ModulesContainer)
    assert isinstance(observer.discovery, DiscoveryService)
    assert len(observer.modules) == 2

    providers = observer.discovery.get_providers(include=[Feature])
    private = [view for view in providers if view.token is PrivateService]
    assert len(private) == 1
    assert private[0].implementation is PrivateService
    assert private[0].instance is not None
    assert all(view.token != "private-alias" for view in providers)
    assert observer.discovery.get_providers(metadata=discoverable) == tuple(private)
    assert observer.discovery.get_providers(metadata=nullable) == tuple(private)
    managed = observer.discovery.get_providers(metadata=managed_marker)
    assert len(managed) == 1
    assert managed[0].implementation is ManagedService
    assert managed[0].instance_created
    assert not isinstance(managed[0].instance, ManagedService)
    none_provider = next(view for view in providers if view.token == "none")
    assert none_provider.instance_created
    assert none_provider.instance is None
    assert none_provider.implementation is type(None)
    assert [view.token for view in observer.discovery.get_controllers()] == [Controller]
    assert constructions == 0

    feature_id = next(
        module_id for module_id in observer.modules if module_id.module is Feature
    )
    alias = observer.modules.provider(feature_id, "private-alias")
    assert alias is not None
    assert alias.ref.token == "private-alias"
    assert alias.canonical.token is PrivateService
    assert isinstance(alias.declaration, AliasProvider)
    assert alias.implementation is PrivateService

    with pytest.raises(ScopeError, match="not visible"):
        await application.resolve(PrivateService)
    missing = ModuleId(type("Missing", (), {}))
    with pytest.raises(ScopeError, match="unknown compiled module"):
        observer.modules[missing]
    with pytest.raises(ScopeError, match="unknown compiled module"):
        observer.modules.provider(missing, "value")
    with pytest.raises(BootstrapError, match="module classes"):
        observer.discovery.get_providers(include=cast(Any, [object()]))
    await application.close()


@pytest.mark.asyncio
async def test_work_scope_run_in_resolves_exact_duplicate_token_owner() -> None:
    class First:
        pass

    class Second:
        pass

    @module(providers=[ClassProvider("shared", First, scope=Scope.REQUEST)])
    class FirstModule:
        pass

    @module(providers=[ClassProvider("shared", Second, scope=Scope.REQUEST)])
    class SecondModule:
        pass

    class Observer:
        def __init__(
            self,
            discovery: DiscoveryService,
            scopes: WorkScopeFactory,
        ) -> None:
            self.discovery = discovery
            self.scopes = scopes

    @module(
        imports=[FirstModule, SecondModule],
        providers=[ClassProvider(Observer)],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    observer = await application.resolve(Observer)
    assert isinstance(observer, Observer)
    shared = [
        provider
        for provider in observer.discovery.get_providers()
        if provider.token == "shared"
    ]
    assert len(shared) == 2

    async def resolve_shared(resolver):
        return await resolver.resolve("shared")

    first = await observer.scopes.run_in(shared[0].ref.module_id, resolve_shared)
    second = await observer.scopes.run_in(shared[1].ref.module_id, resolve_shared)
    assert isinstance(first, First)
    assert isinstance(second, Second)

    with pytest.raises(ScopeError, match="compiled module identity"):
        await observer.scopes.run_in(ModuleId(type("Missing", (), {})), resolve_shared)
    await application.close()
