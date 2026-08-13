from types import MappingProxyType
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from tori_py import AliasProvider, FactoryProvider, Scope, ValueProvider
from tori_py_sqlalchemy import (
    EntityManager,
    SqlAlchemyConfigurationError,
    SqlAlchemyModule,
    SqlAlchemyOptions,
    SqlAlchemySessionOptions,
    get_engine_token,
    get_entity_manager_token,
    get_session_factory_token,
)


def test_options_are_immutable_and_defensively_copy_engine_options() -> None:
    engine_options: dict[str, object] = {"echo": True}
    options = SqlAlchemyOptions(
        url="postgresql+psycopg://localhost/application",
        engine_options=engine_options,
    )
    engine_options["echo"] = False

    assert options.engine_options == {"echo": True}
    assert isinstance(options.engine_options, MappingProxyType)
    with pytest.raises(TypeError):
        cast(Any, options.engine_options)["echo"] = False


def test_options_repr_does_not_expose_url_or_engine_secrets() -> None:
    options = SqlAlchemyOptions(
        url="postgresql+psycopg://member:database-secret@localhost/application",
        engine_options={
            "connect_args": {"password": "connection-secret"},
        },
    )

    rendered = repr(options)
    assert "database-secret" not in rendered
    assert "connection-secret" not in rendered
    assert "member" not in rendered


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"url": ""}, "url"),
        ({"url": cast(Any, 42)}, "url"),
        (
            {
                "url": "postgresql+psycopg://localhost/application",
                "engine_options": cast(Any, []),
            },
            "mapping",
        ),
        (
            {
                "url": "postgresql+psycopg://localhost/application",
                "engine_options": {"url": "other"},
            },
            "must not contain url",
        ),
        (
            {
                "url": "postgresql+psycopg://localhost/application",
                "session": cast(Any, object()),
            },
            "SqlAlchemySessionOptions",
        ),
    ],
)
def test_invalid_options_are_configuration_errors(
    arguments: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(SqlAlchemyConfigurationError, match=message):
        SqlAlchemyOptions(**cast(Any, arguments))


@pytest.mark.parametrize("name", ["expire_on_commit", "autoflush", "autobegin"])
def test_session_flags_require_exact_booleans(name: str) -> None:
    arguments = {name: 1}
    with pytest.raises(SqlAlchemyConfigurationError, match=name):
        SqlAlchemySessionOptions(**cast(Any, arguments))


def test_keyed_tokens_are_stable_distinct_and_validated() -> None:
    tokens = {
        get_engine_token(key="analytics"),
        get_session_factory_token(key="analytics"),
        get_entity_manager_token(key="analytics"),
    }
    assert len(tokens) == 3
    assert get_engine_token(key="analytics") == get_engine_token(key="analytics")
    for key in ("", "static"):
        with pytest.raises(SqlAlchemyConfigurationError, match="key"):
            get_engine_token(key=key)


def test_owned_root_declares_expected_scopes_exports_and_default_aliases() -> None:
    descriptor = SqlAlchemyModule.for_root(
        SqlAlchemyOptions(url="postgresql+psycopg://localhost/application")
    )
    spec = descriptor.factory()
    assert not hasattr(spec, "__await__")
    spec = cast(Any, spec)
    providers = {provider.token: provider for provider in spec.providers}

    assert isinstance(providers[get_engine_token()], FactoryProvider)
    assert providers[get_engine_token()].scope is Scope.SINGLETON
    assert isinstance(providers[get_session_factory_token()], FactoryProvider)
    assert providers[get_session_factory_token()].manage is False
    assert providers[get_entity_manager_token()].scope is Scope.SINGLETON
    assert providers[get_entity_manager_token()].manage is False
    assert isinstance(providers[AsyncEngine], AliasProvider)
    assert isinstance(providers[EntityManager], AliasProvider)
    assert set(spec.exports) == {
        get_engine_token(),
        get_session_factory_token(),
        get_entity_manager_token(),
        AsyncEngine,
        EntityManager,
    }
    assert spec.global_ is True


def test_non_default_root_has_only_qualified_exports() -> None:
    descriptor = SqlAlchemyModule.for_root(
        SqlAlchemyOptions(url="postgresql+psycopg://localhost/analytics"),
        key="analytics",
    )
    spec = cast(Any, descriptor.factory())
    assert set(spec.exports) == {
        get_engine_token(key="analytics"),
        get_session_factory_token(key="analytics"),
        get_entity_manager_token(key="analytics"),
    }
    assert spec.global_ is True
    assert all(
        provider.token not in (AsyncEngine, EntityManager)
        for provider in spec.providers
    )


def test_async_root_registers_factory_without_calling_it_during_materialization() -> (
    None
):
    calls = 0

    async def configure() -> SqlAlchemyOptions:
        nonlocal calls
        calls += 1
        return SqlAlchemyOptions(url="postgresql+psycopg://localhost/application")

    descriptor = SqlAlchemyModule.for_root_async(use_factory=configure)
    spec = cast(Any, descriptor.factory())

    assert calls == 0
    assert spec.imports == ()
    assert any(
        isinstance(provider, FactoryProvider) and provider.factory is configure
        for provider in spec.providers
    )


def test_external_engine_root_uses_unmanaged_value_provider() -> None:
    engine = cast(AsyncEngine, object())
    with pytest.raises(SqlAlchemyConfigurationError, match="AsyncEngine"):
        SqlAlchemyModule.for_engine(engine)

    token_root = SqlAlchemyModule.for_engine("external.engine", key="analytics")
    spec = cast(Any, token_root.factory())
    provider = next(
        provider
        for provider in spec.providers
        if provider.token == get_engine_token(key="analytics")
    )
    assert isinstance(provider, AliasProvider)
    assert provider.target == "external.engine"
    assert not any(isinstance(provider, ValueProvider) for provider in spec.providers)


def test_module_declaration_arguments_are_validated_eagerly() -> None:
    options = SqlAlchemyOptions(url="postgresql+psycopg://localhost/application")
    with pytest.raises(SqlAlchemyConfigurationError, match="options"):
        SqlAlchemyModule.for_root(cast(Any, object()))
    with pytest.raises(SqlAlchemyConfigurationError, match="use_factory"):
        SqlAlchemyModule.for_root_async(use_factory=cast(Any, object()))
    with pytest.raises(SqlAlchemyConfigurationError, match="imports"):
        SqlAlchemyModule.for_root_async(
            use_factory=lambda: options,
            imports=cast(Any, None),
        )
    with pytest.raises(SqlAlchemyConfigurationError, match="global"):
        SqlAlchemyModule.for_root(options, global_=cast(Any, 1))
