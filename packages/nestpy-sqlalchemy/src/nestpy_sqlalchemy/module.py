"""Dynamic Nestpy module for async SQLAlchemy resources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Annotated

from nestpy import (
    AliasProvider,
    DeferredModule,
    FactoryProvider,
    Inject,
    ModuleImport,
    ModuleSpec,
    ProviderDeclaration,
    Scope,
    Token,
    ValueProvider,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from nestpy_sqlalchemy.errors import SqlAlchemyConfigurationError
from nestpy_sqlalchemy.options import SqlAlchemyOptions, SqlAlchemySessionOptions
from nestpy_sqlalchemy.runtime import (
    _new_session_factory,
    _owned_engine_factory,
    _scoped_session_factory,
    _session_factory_factory,
)
from nestpy_sqlalchemy.tokens import (
    _options_token,
    get_engine_token,
    get_session_factory_token,
    get_session_token,
)

type SqlAlchemyOptionsFactory = Callable[
    ..., SqlAlchemyOptions | Awaitable[SqlAlchemyOptions]
]

_DEFAULT_SESSION_OPTIONS = SqlAlchemySessionOptions()


class SqlAlchemyModule:
    """Compose one keyed async engine, session factory, and scoped session."""

    @classmethod
    def for_root(
        cls,
        options: SqlAlchemyOptions,
        *,
        key: str = "default",
        global_: bool = False,
    ) -> DeferredModule:
        if not isinstance(options, SqlAlchemyOptions):
            raise SqlAlchemyConfigurationError("options must be SqlAlchemyOptions")
        _validate_common(key=key, global_=global_)
        options_token = _options_token(key)

        def materialize() -> ModuleSpec:
            return _owned_root_spec(
                ValueProvider(options_token, options),
                imports=(),
                key=key,
                global_=global_,
                session=options.session,
            )

        return DeferredModule(cls, key, materialize)

    @classmethod
    def for_root_async(
        cls,
        *,
        use_factory: SqlAlchemyOptionsFactory,
        imports: Iterable[ModuleImport] = (),
        key: str = "default",
        global_: bool = False,
    ) -> DeferredModule:
        if not callable(use_factory):
            raise SqlAlchemyConfigurationError("use_factory must be callable")
        _validate_common(key=key, global_=global_)
        imported = _imports(imports)
        options_token = _options_token(key)

        def materialize() -> ModuleSpec:
            return _owned_root_spec(
                FactoryProvider(options_token, use_factory, manage=False),
                imports=imported,
                key=key,
                global_=global_,
                session=None,
            )

        return DeferredModule(cls, key, materialize)

    @classmethod
    def for_engine(
        cls,
        engine: AsyncEngine | Token,
        *,
        session: SqlAlchemySessionOptions = _DEFAULT_SESSION_OPTIONS,
        imports: Iterable[ModuleImport] = (),
        key: str = "default",
        global_: bool = False,
    ) -> DeferredModule:
        if not isinstance(session, SqlAlchemySessionOptions):
            raise SqlAlchemyConfigurationError(
                "session must be SqlAlchemySessionOptions"
            )
        _validate_common(key=key, global_=global_)
        imported = _imports(imports)
        engine_token = get_engine_token(key=key)
        source_token: Token | None = None
        if isinstance(engine, str | type):
            source_token = engine
            engine_provider: ProviderDeclaration | None = (
                None
                if source_token == engine_token
                else AliasProvider(engine_token, source_token)
            )
        elif isinstance(engine, AsyncEngine):
            engine_provider = ValueProvider(engine_token, engine)
        else:
            raise SqlAlchemyConfigurationError(
                "engine must be an AsyncEngine or provider token"
            )

        def materialize() -> ModuleSpec:
            providers: list[ProviderDeclaration] = (
                [] if engine_provider is None else [engine_provider]
            )
            providers.extend(
                _session_providers(
                    engine_token=engine_token,
                    key=key,
                    session=session,
                )
            )
            exports = _exports(key)
            if key == "default":
                if source_token is not AsyncEngine:
                    providers.append(AliasProvider(AsyncEngine, engine_token))
                providers.append(
                    AliasProvider(AsyncSession, get_session_token(key=key))
                )
            return ModuleSpec(
                imports=imported,
                providers=providers,
                exports=exports,
                global_=global_,
            )

        return DeferredModule(cls, key, materialize)


def _owned_root_spec(
    options_provider: ProviderDeclaration,
    *,
    imports: tuple[ModuleImport, ...],
    key: str,
    global_: bool,
    session: SqlAlchemySessionOptions | None,
) -> ModuleSpec:
    options_token = _options_token(key)
    engine_token = get_engine_token(key=key)
    providers: list[ProviderDeclaration] = [
        options_provider,
        FactoryProvider(engine_token, _owned_engine_factory(options_token)),
    ]
    providers.extend(
        _session_providers(
            engine_token=engine_token,
            key=key,
            session=session,
            options_token=options_token,
        )
    )
    if key == "default":
        providers.extend(
            (
                AliasProvider(AsyncEngine, engine_token),
                AliasProvider(AsyncSession, get_session_token(key=key)),
            )
        )
    return ModuleSpec(
        imports=imports,
        providers=providers,
        exports=_exports(key),
        global_=global_,
    )


def _session_providers(
    *,
    engine_token: Token,
    key: str,
    session: SqlAlchemySessionOptions | None,
    options_token: Token | None = None,
) -> list[ProviderDeclaration]:
    session_factory_token = get_session_factory_token(key=key)
    session_token = get_session_token(key=key)
    if session is None:
        if options_token is None:
            raise AssertionError("runtime options token is required")
        session_factory = _runtime_session_factory_factory(
            engine_token,
            options_token,
        )
    else:
        session_factory = _session_factory_factory(engine_token, session)
    return [
        FactoryProvider(
            session_factory_token,
            session_factory,
            manage=False,
        ),
        FactoryProvider(
            session_token,
            _scoped_session_factory(session_factory_token),
            scope=Scope.REQUEST,
        ),
    ]


def _runtime_session_factory_factory(engine_token: Token, options_token: Token):
    def create(engine, options):
        if not isinstance(options, SqlAlchemyOptions):
            raise SqlAlchemyConfigurationError(
                "SQLAlchemy options factory must return SqlAlchemyOptions"
            )
        return _new_session_factory(engine, options.session)

    create.__annotations__ = {
        "engine": Annotated[AsyncEngine, Inject(engine_token)],
        "options": Annotated[SqlAlchemyOptions, Inject(options_token)],
    }
    return create


def _exports(key: str) -> tuple[Token, ...]:
    exports: list[Token] = [
        get_engine_token(key=key),
        get_session_factory_token(key=key),
        get_session_token(key=key),
    ]
    if key == "default":
        exports.extend((AsyncEngine, AsyncSession))
    return tuple(exports)


def _imports(imports: Iterable[ModuleImport]) -> tuple[ModuleImport, ...]:
    try:
        return tuple(imports)
    except TypeError as error:
        raise SqlAlchemyConfigurationError("imports must be iterable") from error


def _validate_common(*, key: str, global_: bool) -> None:
    get_engine_token(key=key)
    if not isinstance(global_, bool):
        raise SqlAlchemyConfigurationError("global_ must be boolean")


__all__ = ["SqlAlchemyModule", "SqlAlchemyOptionsFactory"]
