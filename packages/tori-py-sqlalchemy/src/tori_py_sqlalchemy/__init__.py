"""Async SQLAlchemy lifecycle and DI integration for ToriPy."""

from tori_py_sqlalchemy.errors import (
    SqlAlchemyConfigurationError,
    SqlAlchemyIntegrationError,
    TransactionContextError,
)
from tori_py_sqlalchemy.managers import EntityManager, ExecuteParams
from tori_py_sqlalchemy.module import SqlAlchemyModule, SqlAlchemyOptionsFactory
from tori_py_sqlalchemy.options import SqlAlchemyOptions, SqlAlchemySessionOptions
from tori_py_sqlalchemy.repository import Repository, repository
from tori_py_sqlalchemy.tokens import (
    get_engine_token,
    get_entity_manager_token,
    get_repository_token,
    get_session_factory_token,
    inject_repository,
)

__all__ = [
    "EntityManager",
    "ExecuteParams",
    "Repository",
    "SqlAlchemyConfigurationError",
    "SqlAlchemyIntegrationError",
    "SqlAlchemyModule",
    "SqlAlchemyOptions",
    "SqlAlchemyOptionsFactory",
    "SqlAlchemySessionOptions",
    "TransactionContextError",
    "get_entity_manager_token",
    "get_engine_token",
    "get_repository_token",
    "get_session_factory_token",
    "inject_repository",
    "repository",
]
