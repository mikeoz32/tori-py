from dataclasses import FrozenInstanceError
from typing import Annotated, cast

import pytest
from tori_py import (
    AliasProvider,
    ApplicationOptions,
    BootstrapError,
    ClassProvider,
    DeferredModule,
    ExecutionContext,
    FactoryProvider,
    Inject,
    ModuleSpec,
    PipelineOptions,
    ProviderDeclaration,
    Scope,
    ScopedResolver,
    ValueProvider,
    controller,
    get,
    get_controller_metadata,
    get_module_metadata,
    get_no_body_metadata,
    get_route_metadata,
    injectable,
    module,
    no_body,
)
from tori_py.starlette import StarletteOptions


class _Resolver:
    async def resolve(self, token: str) -> object:
        return token

    async def resolve_ref(self, ref: object) -> object:
        return ref


class _Context:
    application_id = "app"
    module_id = "module"
    route_id = "route"
    request_id = "request"
    resolver = _Resolver()
    metadata = {}
    execution_kind = "test"


def test_provider_declarations_are_immutable_and_structural() -> None:
    provider = ValueProvider("settings", object())

    with pytest.raises(FrozenInstanceError):
        provider.__setattr__("token", "other")

    assert provider.scope is Scope.SINGLETON
    assert ClassProvider(str).use_class is str
    assert FactoryProvider("factory", lambda: object()).manage is True
    assert AliasProvider("reader", "repository").target == "repository"
    assert Inject("repository").token == "repository"


def test_injectable_decorator_preserves_identity_and_rejects_duplicates() -> None:
    class Service:
        pass

    original = Service
    decorated = injectable(scope=Scope.REQUEST, manage=False)(Service)

    assert decorated is original
    with pytest.raises(BootstrapError, match="already declared"):
        injectable()(decorated)

    with pytest.raises(BootstrapError, match="manage must be boolean"):
        injectable(manage=cast(bool, "yes"))


def test_execution_context_protocol_is_driver_neutral() -> None:
    context = _Context()
    assert isinstance(context, ExecutionContext)
    assert isinstance(context.resolver, ScopedResolver)
    assert context.application_id == "app"
    assert context.module_id == "module"
    assert context.route_id == "route"
    assert context.request_id == "request"
    assert context.execution_kind == "test"
    assert set(context.metadata) == set()


def test_global_pipeline_options_are_not_starlette_transport_options() -> None:
    class Guard:
        async def can_activate(self, context) -> bool:
            return True

    guard = Guard()
    pipeline = PipelineOptions(guards=(guard,))
    assert pipeline.guards == (guard,)
    assert not hasattr(StarletteOptions(), "guards")


def test_invalid_declarations_fail_without_runtime_work() -> None:
    with pytest.raises(BootstrapError, match="non-empty string"):
        ValueProvider("", object())
    with pytest.raises(BootstrapError, match="only have singleton"):
        ValueProvider("value", object(), scope=Scope.REQUEST)
    with pytest.raises(BootstrapError, match="exceeds shutdown"):
        ApplicationOptions(shutdown_timeout=1, cleanup_reserve=1, cancellation_grace=1)
    with pytest.raises(BootstrapError, match="cannot be negative"):
        StarletteOptions(body_size_limit=-1)
    with pytest.raises(BootstrapError, match="must be a number"):
        ApplicationOptions(shutdown_timeout=cast(float, "30"))
    with pytest.raises(BootstrapError, match="must be an integer"):
        StarletteOptions(body_size_limit=cast(int, 1.5))
    with pytest.raises(BootstrapError, match="HTTP status"):
        from tori_py import StatusMetadata

        StatusMetadata(cast(int, 200.5))


def test_module_metadata_is_direct_immutable_and_has_no_registry() -> None:
    class ExampleModule:
        pass

    original = ExampleModule
    decorated_module = module(providers=[ValueProvider("value", 1)], exports=["value"])(
        ExampleModule
    )
    assert decorated_module is original

    metadata = get_module_metadata(decorated_module)
    assert metadata is not None
    provider = cast(ProviderDeclaration, tuple(metadata.providers)[0])
    assert provider.token == "value"
    assert metadata.exports == ("value",)
    assert get_module_metadata(type("Child", (decorated_module,), {})) is None

    with pytest.raises(BootstrapError, match="already declared"):
        module()(decorated_module)


def test_alias_and_decorator_metadata_restrictions() -> None:
    alias = AliasProvider("reader", "repository")
    assert not hasattr(alias, "manage")
    assert not hasattr(alias, "scope")

    @controller()
    class Controller:
        @get("/")
        async def index(self) -> str:
            return "ok"

    with pytest.raises(BootstrapError, match="already declared"):
        controller()(Controller)
    with pytest.raises(BootstrapError, match="already declared"):
        get("/other")(Controller.index)


def test_controller_and_route_decorators_preserve_identity() -> None:
    async def list_users(
        value: Annotated[str, Inject("value")],
    ) -> str:
        return value

    original_method = list_users
    list_users = get("/")(list_users)
    assert list_users is original_method

    @controller("/users")
    class UsersController:
        @get("/class")
        async def class_route(self) -> str:
            return "ok"

    controller_metadata = get_controller_metadata(UsersController)
    route_metadata = get_route_metadata(UsersController.class_route)
    assert controller_metadata is not None
    assert route_metadata is not None
    assert controller_metadata.prefix == "/users"
    assert route_metadata.method == "GET"
    assert UsersController.class_route.__name__ == "class_route"


def test_no_body_metadata_is_direct_opt_in_and_rejects_duplicates() -> None:
    async def empty() -> None:
        pass

    original = empty
    empty = no_body(empty)

    assert empty is original
    assert get_no_body_metadata(empty) is not None
    with pytest.raises(BootstrapError, match="already declared"):
        no_body(empty)


def test_module_spec_freezes_iterables_and_deferred_descriptor() -> None:
    class DynamicModule:
        pass

    async def materialize() -> ModuleSpec:
        return ModuleSpec()

    descriptor = DeferredModule(DynamicModule, "configured", materialize)
    spec = ModuleSpec(imports=[descriptor], providers=[ValueProvider("x", 1)])

    assert spec.imports == (descriptor,)
    provider = cast(ProviderDeclaration, tuple(spec.providers)[0])
    assert provider.token == "x"
