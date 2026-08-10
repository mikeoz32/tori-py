import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Annotated, Any, cast
from unittest.mock import create_autospec

import nestpy_sqlalchemy.runtime as sqlalchemy_runtime
import pytest
from nestpy import ClassProvider, Inject, ValueProvider, module
from nestpy.testing import TestingModule
from nestpy_sqlalchemy import (
    EntityManager,
    SqlAlchemyConfigurationError,
    SqlAlchemyModule,
    SqlAlchemyOptions,
    get_engine_token,
    get_entity_manager_token,
    get_session_factory_token,
)
from sqlalchemy.ext.asyncio import AsyncEngine


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
        self.commit_calls = 0
        self.rollback_calls = 0
        self.transaction_exit_error: BaseException | None = None

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

    def begin(self) -> _FakeTransactionContext:
        return _FakeTransactionContext(self)

    async def scalar(self, statement: object, params: object = None) -> object:
        del params
        if isinstance(statement, BaseException):
            raise statement
        return statement


class _FakeTransactionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        if exc_type is None:
            self._session.commit_calls += 1
        else:
            self._session.rollback_calls += 1
        if self._session.transaction_exit_error is not None:
            raise self._session.transaction_exit_error


class _FakeSessionFactory:
    def __init__(self) -> None:
        self.sessions: list[_FakeSession] = []

    def __call__(self) -> _FakeSession:
        session = _FakeSession()
        self.sessions.append(session)
        return session

    def begin(self) -> _FakeTransactionContext:
        raise AssertionError("EntityManager must own the outer session context")


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
async def test_owned_engine_and_singleton_managers_follow_application_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes = _install_fakes(monkeypatch)
    database = SqlAlchemyModule.for_root(
        SqlAlchemyOptions(
            url="postgresql+psycopg://localhost/application",
            engine_options={"echo": True},
        )
    )

    @module(imports=[database])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    try:
        engine = await application.resolve(get_engine_token())
        entities = cast(EntityManager, await application.resolve(EntityManager))
        assert engine is fakes.engines[0]
        assert await application.resolve(AsyncEngine) is engine
        assert await application.resolve(get_entity_manager_token()) is entities
        assert fakes.session_factories[0].sessions == []
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

        async with entities.transaction() as transaction:
            assert transaction is entities
        failure = RuntimeError("transaction failed")
        with pytest.raises(RuntimeError, match="transaction failed"):
            async with entities.transaction():
                raise failure

        opened = fakes.session_factories[0].sessions
        assert [session.exit_calls for session in opened] == [1, 1]
        assert [session.commit_calls for session in opened] == [1, 0]
        assert [session.rollback_calls for session in opened] == [0, 1]
    finally:
        await application.close()

    assert fakes.engines[0].dispose_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body_error", [None, RuntimeError("body failed")])
async def test_transaction_closes_session_when_finalization_fails(
    body_error: RuntimeError | None,
) -> None:
    factory = _FakeSessionFactory()
    entities = EntityManager(cast(Any, factory))
    finalization_error = RuntimeError("transaction finalization failed")

    with pytest.raises(RuntimeError, match="transaction finalization failed"):
        async with entities.transaction():
            fake_session = cast(_FakeSession, entities._require_session())
            fake_session.transaction_exit_error = finalization_error
            if body_error is not None:
                raise body_error

    opened = factory.sessions[0]
    assert opened.exit_calls == 1
    assert opened.commit_calls == (body_error is None)
    assert opened.rollback_calls == (body_error is not None)
    async with entities.transaction():
        pass


@pytest.mark.asyncio
async def test_transaction_closes_session_when_task_is_cancelled() -> None:
    factory = _FakeSessionFactory()
    entities = EntityManager(cast(Any, factory))
    entered = asyncio.Event()

    async def operation() -> None:
        async with entities.transaction():
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(operation())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    opened = factory.sessions[0]
    assert opened.exit_calls == 1
    assert opened.commit_calls == 0
    assert opened.rollback_calls == 1
    async with entities.transaction():
        pass


@pytest.mark.asyncio
async def test_automatic_operations_commit_rollback_and_close_exactly_once() -> None:
    factory = _FakeSessionFactory()
    entities = EntityManager(cast(Any, factory))

    assert await entities.scalar(cast(Any, 7)) == 7
    failure = RuntimeError("operation failed")
    with pytest.raises(RuntimeError, match="operation failed") as captured:
        await entities.scalar(cast(Any, failure))
    assert captured.value is failure

    assert [session.commit_calls for session in factory.sessions] == [1, 0]
    assert [session.rollback_calls for session in factory.sessions] == [0, 1]
    assert [session.exit_calls for session in factory.sessions] == [1, 1]


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
        assert fakes.engine_calls == [(config.url, {"pool_pre_ping": True})]
        assert await application.resolve(get_session_factory_token())
        assert await application.resolve(EntityManager)
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_for_root_async_accepts_sync_factory_and_explicit_token(
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
async def test_default_and_named_roots_have_isolated_singleton_managers(
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
        primary = await application.resolve(EntityManager)
        analytics = await application.resolve(get_entity_manager_token(key="analytics"))
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
        assert await application.resolve(EntityManager)
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
