"""Internal SQLAlchemy resource factories."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from nestpy import Inject, Token
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from nestpy_sqlalchemy.errors import SqlAlchemyConfigurationError
from nestpy_sqlalchemy.options import SqlAlchemyOptions, SqlAlchemySessionOptions


def _owned_engine_factory(options_token: Token):
    def create(options):
        if not isinstance(options, SqlAlchemyOptions):
            raise SqlAlchemyConfigurationError(
                "SQLAlchemy options factory must return SqlAlchemyOptions"
            )
        return _owned_engine(options)

    create.__annotations__ = {
        "options": Annotated[SqlAlchemyOptions, Inject(options_token)]
    }
    return create


@asynccontextmanager
async def _owned_engine(options: SqlAlchemyOptions) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(options.url, **dict(options.engine_options))
    try:
        yield engine
    finally:
        await engine.dispose()


def _session_factory_factory(
    engine_token: Token,
    options: SqlAlchemySessionOptions,
):
    def create(engine):
        return _new_session_factory(engine, options)

    create.__annotations__ = {"engine": Annotated[AsyncEngine, Inject(engine_token)]}
    return create


def _new_session_factory(
    engine: AsyncEngine,
    options: SqlAlchemySessionOptions,
) -> async_sessionmaker[AsyncSession]:
    if not isinstance(engine, AsyncEngine):
        raise SqlAlchemyConfigurationError(
            "engine provider must resolve to AsyncEngine"
        )
    return async_sessionmaker(
        engine,
        expire_on_commit=options.expire_on_commit,
        autoflush=options.autoflush,
        autobegin=options.autobegin,
    )


def _scoped_session_factory(session_factory_token: Token):
    def create(factory):
        return _scoped_session(factory)

    create.__annotations__ = {
        "factory": Annotated[object, Inject(session_factory_token)]
    }
    return create


@asynccontextmanager
async def _scoped_session(factory: Any) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session


__all__: list[str] = []
