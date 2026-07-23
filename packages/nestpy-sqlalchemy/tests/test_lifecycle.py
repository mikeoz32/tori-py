from collections.abc import Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Annotated, Any, cast
from unittest.mock import create_autospec

import nestpy_sqlalchemy.runtime as sqlalchemy_runtime
import pytest
from nestpy import (
    ClassProvider,
    Inject,
    ScopedResolver,
    ScopeError,
    ValueProvider,
    WorkScopeFactory,
    module,
)
from nestpy.testing import TestingModule
from nestpy_sqlalchemy import (
    SqlAlchemyConfigurationError,
    SqlAlchemyModule,
    SqlAlchemyOptions,
    get_engine_token,
    get_session_factory_token,
    get_session_token,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


class _FakeEngine(AsyncEngine):
    def __init__(self) -> None:
        self.dispose_calls = 0

    async def dispose(self, close: bool = True) -> None:
        del close
        self.dispose_calls += 1


class _FakeSession:
    def __init__(self) -> None:
        self.enter_calls = 0
        self.exit_calls = 0

    async def __aenter__(self) -> _FakeSession:
        self.enter_calls += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        self.exit_calls += 1


class _FakeSessionFactory:
    def __init__(self) -> None:
        self.sessions: list[_FakeSession] = []

    def __call__(self) -> _FakeSession:
        session = _FakeSession()
        self.sessions.append(session)
        return session


class _ScopeRunner:
    def __init__(self, scopes: WorkScopeFactory) -> None:
        self.scopes = scopes


@dataclass(slots=True)
class _Fakes:
    engines: list[_FakeEngine]
    engine_calls: list[tuple[object, Mapping[str, object]]]
    session_factory_calls: list[tuple[object, Mapping[str, object]]]
    session_factories: list[_FakeSessionFactory]


def _install_fakes(monkeypatch: pytest.MonkeyPatch) -> _Fakes:
    fakes = _Fakes([], [], [], [])

    def create_engine(url: object, **options: object) -> _FakeEngine:
        engine = _FakeEngine()
        fakes.engines.append(engine)
        fakes.engine_calls.append((url, dict(options)))
        return engine

    def create_session_factory(
        engine: object,
        **options: object,
    ) -> _FakeSessionFactory:
        factory = _FakeSessionFactory()
        fakes.session_factories.append(factory)
        fakes.session_factory_calls.append((engine, dict(options)))
        return factory

    monkeypatch.setattr(sqlalchemy_runtime, "create_async_engine", create_engine)
    monkeypatch.setattr(
        sqlalchemy_runtime,
        "async_sessionmaker",
        create_session_factory,
    )
    return fakes


@pytest.mark.asyncio
async def test_owned_engine_and_scoped_sessions_follow_application_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes = _install_fakes(monkeypatch)
    database = SqlAlchemyModule.for_root(
        SqlAlchemyOptions(
            url="postgresql+psycopg://localhost/application",
            engine_options={"echo": True},
        )
    )

    @module(imports=[database], providers=[ClassProvider(_ScopeRunner)])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    try:
        engine = await application.resolve(get_engine_token())
        assert engine is fakes.engines[0]
        assert await application.resolve(AsyncEngine) is engine
        assert len(fakes.engine_calls) == 1
        assert fakes.engine_calls[0][1] == {"echo": True}
        assert fakes.session_factory_calls == [
            (
                engine,
                {
                    "expire_on_commit": False,
                    "autoflush": False,
                    "autobegin": False,
                },
            )
        ]
        with pytest.raises(ScopeError):
            await application.resolve(AsyncSession)

        runner = cast(_ScopeRunner, await application.resolve(_ScopeRunner))

        async def resolve_session(resolver: ScopedResolver) -> object:
            qualified = await resolver.resolve(get_session_token())
            assert await resolver.resolve(get_session_token()) is qualified
            assert await resolver.resolve(AsyncSession) is qualified
            return qualified

        first = await runner.scopes.run(resolve_session)
        second = await runner.scopes.run(resolve_session)
        assert first is not second
        assert [
            session.exit_calls for session in fakes.session_factories[0].sessions
        ] == [
            1,
            1,
        ]
    finally:
        await application.close()

    assert fakes.engines[0].dispose_calls == 1


class _Config:
    def __init__(self, url: str) -> None:
        self.url = url


@pytest.mark.asyncio
async def test_for_root_async_resolves_config_service_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes = _install_fakes(monkeypatch)
    config = _Config("postgresql+psycopg://localhost/configured")
    calls = 0

    async def configure(settings: _Config) -> SqlAlchemyOptions:
        nonlocal calls
        calls += 1
        return SqlAlchemyOptions(
            url=settings.url,
            engine_options={"pool_pre_ping": True},
        )

    @module(providers=[ValueProvider(_Config, config)], exports=[_Config])
    class ConfigModule:
        pass

    database = SqlAlchemyModule.for_root_async(
        imports=[ConfigModule],
        use_factory=configure,
    )

    @module(imports=[database])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    try:
        assert calls == 1
        assert fakes.engine_calls == [
            (
                config.url,
                {"pool_pre_ping": True},
            )
        ]
        assert await application.resolve(get_session_factory_token())
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_for_root_async_accepts_synchronous_options_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes = _install_fakes(monkeypatch)
    config = _Config("postgresql+psycopg://localhost/synchronous")

    def configure(settings: _Config) -> SqlAlchemyOptions:
        return SqlAlchemyOptions(url=settings.url)

    @module(providers=[ValueProvider(_Config, config)], exports=[_Config])
    class ConfigModule:
        pass

    database = SqlAlchemyModule.for_root_async(
        imports=[ConfigModule],
        use_factory=configure,
    )

    @module(imports=[database])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    try:
        assert fakes.engine_calls[0][0] == config.url
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_for_root_async_supports_explicit_config_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes = _install_fakes(monkeypatch)
    config_token = "application.database.config"
    config = _Config("postgresql+psycopg://localhost/explicit-token")

    def configure(
        settings: Annotated[_Config, Inject(config_token)],
    ) -> SqlAlchemyOptions:
        return SqlAlchemyOptions(url=settings.url)

    @module(
        providers=[ValueProvider(config_token, config)],
        exports=[config_token],
    )
    class ConfigModule:
        pass

    database = SqlAlchemyModule.for_root_async(
        imports=[ConfigModule],
        use_factory=configure,
    )

    @module(imports=[database])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    try:
        assert fakes.engine_calls[0][0] == config.url
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_invalid_async_options_result_fails_before_engine_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes = _install_fakes(monkeypatch)

    def configure() -> Any:
        return object()

    database = SqlAlchemyModule.for_root_async(use_factory=configure)

    @module(imports=[database])
    class Root:
        pass

    with pytest.raises(SqlAlchemyConfigurationError, match="must return"):
        await TestingModule.create(Root).compile()
    assert fakes.engines == []


@pytest.mark.asyncio
async def test_startup_failure_disposes_acquired_owned_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes = _install_fakes(monkeypatch)
    database = SqlAlchemyModule.for_root(
        SqlAlchemyOptions(url="postgresql+psycopg://localhost/application")
    )

    class FailingService:
        def __init__(self, engine: AsyncEngine) -> None:
            del engine
            raise RuntimeError("startup failed")

    @module(imports=[database], providers=[ClassProvider(FailingService)])
    class Root:
        pass

    with pytest.raises(RuntimeError, match="startup failed"):
        await TestingModule.create(Root).compile()
    assert len(fakes.engines) == 1
    assert fakes.engines[0].dispose_calls == 1


@pytest.mark.asyncio
async def test_external_engine_is_not_disposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes = _install_fakes(monkeypatch)
    external = create_autospec(AsyncEngine, instance=True)
    database = SqlAlchemyModule.for_engine(external)

    @module(imports=[database])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    try:
        assert await application.resolve(get_engine_token()) is external
        assert fakes.engines == []
    finally:
        await application.close()
    external.dispose.assert_not_awaited()


@pytest.mark.asyncio
async def test_default_and_named_roots_are_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes = _install_fakes(monkeypatch)
    default_database = SqlAlchemyModule.for_root(
        SqlAlchemyOptions(url="postgresql+psycopg://localhost/primary")
    )
    analytics_database = SqlAlchemyModule.for_root(
        SqlAlchemyOptions(url="postgresql+psycopg://localhost/analytics"),
        key="analytics",
    )

    @module(imports=[default_database, analytics_database])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    try:
        primary = await application.resolve(AsyncEngine)
        analytics = await application.resolve(get_engine_token(key="analytics"))
        assert primary is not analytics
        assert {call[0] for call in fakes.engine_calls} == {
            "postgresql+psycopg://localhost/primary",
            "postgresql+psycopg://localhost/analytics",
        }
    finally:
        await application.close()
    assert [engine.dispose_calls for engine in fakes.engines] == [1, 1]


@pytest.mark.asyncio
async def test_external_engine_token_is_resolved_without_transferring_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes = _install_fakes(monkeypatch)
    external = create_autospec(AsyncEngine, instance=True)

    @module(
        providers=[ValueProvider(AsyncEngine, external)],
        exports=[AsyncEngine],
    )
    class ExternalEngineModule:
        pass

    database = SqlAlchemyModule.for_engine(
        AsyncEngine,
        imports=[ExternalEngineModule],
    )

    @module(imports=[database])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    try:
        assert await application.resolve(get_engine_token()) is external
        assert await application.resolve(AsyncEngine) is external
        assert fakes.engines == []
    finally:
        await application.close()
    external.dispose.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_engine_token_is_validated_during_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fakes(monkeypatch)

    @module(
        providers=[ValueProvider("external.engine", object())],
        exports=["external.engine"],
    )
    class ExternalEngineModule:
        pass

    database = SqlAlchemyModule.for_engine(
        "external.engine",
        imports=[ExternalEngineModule],
    )

    @module(imports=[database])
    class Root:
        pass

    with pytest.raises(SqlAlchemyConfigurationError, match="AsyncEngine"):
        await TestingModule.create(Root).compile()


@pytest.mark.asyncio
async def test_session_cleanup_runs_when_work_scope_body_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes = _install_fakes(monkeypatch)
    database = SqlAlchemyModule.for_root(
        SqlAlchemyOptions(url="postgresql+psycopg://localhost/application")
    )

    @module(imports=[database], providers=[ClassProvider(_ScopeRunner)])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    try:
        runner = cast(_ScopeRunner, await application.resolve(_ScopeRunner))
        failure = RuntimeError("operation failed")

        async def operation(resolver: ScopedResolver) -> None:
            await resolver.resolve(get_session_token())
            raise failure

        with pytest.raises(RuntimeError, match="operation failed") as captured:
            await runner.scopes.run(operation)
        assert captured.value is failure
        session = fakes.session_factories[0].sessions[0]
        assert session.exit_calls == 1
    finally:
        await application.close()
