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
from nestpy_sqlalchemy.managers import EntityManager
from nestpy_sqlalchemy.options import SqlAlchemyOptions, SqlAlchemySessionOptions
from nestpy_sqlalchemy.repository import Repository


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


def _entity_manager_factory(session_factory_token: Token):
    def create(factory):
        if not callable(factory) or not callable(getattr(factory, "begin", None)):
            raise SqlAlchemyConfigurationError(
                "session factory provider must resolve to async_sessionmaker-like value"
            )
        return EntityManager(factory)

    create.__annotations__ = {
        "factory": Annotated[object, Inject(session_factory_token)]
    }
    return create


def _repository_factory(
    repository_type: type[Repository[Any]],
    entity_type: type[object],
    entity_manager_token: Token,
):
    def create(entities):
        if not isinstance(entities, EntityManager):
            raise SqlAlchemyConfigurationError(
                "entity manager provider must resolve to EntityManager"
            )
        return repository_type(entity_type, entities)

    create.__annotations__ = {
        "entities": Annotated[EntityManager, Inject(entity_manager_token)]
    }
    return create


__all__: list[str] = []
