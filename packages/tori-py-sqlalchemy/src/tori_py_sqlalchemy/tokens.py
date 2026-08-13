"""Stable public tokens for keyed SQLAlchemy roots and mapped classes."""

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Mapper
from tori_py import Inject, Token

from tori_py_sqlalchemy.errors import SqlAlchemyConfigurationError


def _keyed(kind: str, key: str) -> Token:
    if not isinstance(key, str) or not key or key == "static":
        raise SqlAlchemyConfigurationError(
            "SQLAlchemy key must be non-empty and not 'static'"
        )
    return f"tori_py_sqlalchemy:{key}:{kind}"


def _options_token(key: str) -> Token:
    return _keyed("private_options", key)


def get_engine_token(*, key: str = "default") -> Token:
    """Return the qualified async-engine token for one database root."""

    return _keyed("engine", key)


def get_session_factory_token(*, key: str = "default") -> Token:
    """Return the qualified async-sessionmaker token for one database root."""

    return _keyed("session_factory", key)


def get_entity_manager_token(*, key: str = "default") -> Token:
    """Return the qualified singleton EntityManager token for one root."""

    return _keyed("entity_manager", key)


def get_repository_token(entity_type: type[object], *, key: str = "default") -> Token:
    """Return the process-local identity token for one mapped class repository."""

    _validate_entity_type(entity_type)
    entity_name = f"{entity_type.__module__}.{entity_type.__qualname__}"
    return _keyed(f"repository:{entity_name}:{id(entity_type):x}", key)


def inject_repository(
    entity_type: type[object],
    *,
    key: str = "default",
) -> Inject:
    """Create a standard ToriPy marker for one default repository."""

    return Inject(get_repository_token(entity_type, key=key))


def _validate_entity_type(entity_type: type[object]) -> None:
    if not isinstance(entity_type, type):
        raise SqlAlchemyConfigurationError("repository entity must be a class")
    inspected = sa_inspect(entity_type, raiseerr=False)
    if not isinstance(inspected, Mapper):
        raise SqlAlchemyConfigurationError(
            "repository entity must be a mapped SQLAlchemy class"
        )


__all__ = [
    "get_entity_manager_token",
    "get_engine_token",
    "get_repository_token",
    "get_session_factory_token",
    "inject_repository",
]
