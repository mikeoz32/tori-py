"""Deterministic public tokens for keyed SQLAlchemy roots."""

from nestpy import Token

from nestpy_sqlalchemy.errors import SqlAlchemyConfigurationError


def _keyed(kind: str, key: str) -> Token:
    if not isinstance(key, str) or not key or key == "static":
        raise SqlAlchemyConfigurationError(
            "SQLAlchemy key must be non-empty and not 'static'"
        )
    return f"nestpy_sqlalchemy:{key}:{kind}"


def _options_token(key: str) -> Token:
    return _keyed("private_options", key)


def get_engine_token(*, key: str = "default") -> Token:
    """Return the qualified async-engine token for one database root."""

    return _keyed("engine", key)


def get_session_factory_token(*, key: str = "default") -> Token:
    """Return the qualified async-sessionmaker token for one database root."""

    return _keyed("session_factory", key)


def get_session_manager_token(*, key: str = "default") -> Token:
    """Return the qualified singleton SessionManager token for one root."""

    return _keyed("session_manager", key)


def get_entity_manager_token(*, key: str = "default") -> Token:
    """Return the qualified singleton EntityManager token for one root."""

    return _keyed("entity_manager", key)


__all__ = [
    "get_entity_manager_token",
    "get_engine_token",
    "get_session_factory_token",
    "get_session_manager_token",
]
