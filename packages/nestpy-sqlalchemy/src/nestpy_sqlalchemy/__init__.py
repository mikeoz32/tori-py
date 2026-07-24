"""Async SQLAlchemy lifecycle and DI integration for Nestpy."""

from nestpy_sqlalchemy.errors import (
    RepositoryBindingError,
    SqlAlchemyConfigurationError,
    SqlAlchemyIntegrationError,
)
from nestpy_sqlalchemy.managers import (
    EntityManager,
    EntityTransaction,
    ExecuteParams,
    SessionManager,
)
from nestpy_sqlalchemy.module import SqlAlchemyModule, SqlAlchemyOptionsFactory
from nestpy_sqlalchemy.options import SqlAlchemyOptions, SqlAlchemySessionOptions
from nestpy_sqlalchemy.repository import Repository, repository
from nestpy_sqlalchemy.tokens import (
    get_engine_token,
    get_entity_manager_token,
    get_repository_token,
    get_session_factory_token,
    get_session_manager_token,
    inject_repository,
)

__all__ = [
    "EntityManager",
    "EntityTransaction",
    "ExecuteParams",
    "Repository",
    "RepositoryBindingError",
    "SessionManager",
    "SqlAlchemyConfigurationError",
    "SqlAlchemyIntegrationError",
    "SqlAlchemyModule",
    "SqlAlchemyOptions",
    "SqlAlchemyOptionsFactory",
    "SqlAlchemySessionOptions",
    "get_entity_manager_token",
    "get_engine_token",
    "get_repository_token",
    "get_session_factory_token",
    "get_session_manager_token",
    "inject_repository",
    "repository",
]
