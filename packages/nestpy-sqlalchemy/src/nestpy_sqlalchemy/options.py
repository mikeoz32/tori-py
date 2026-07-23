"""Immutable engine and session configuration."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from sqlalchemy.engine import URL

from nestpy_sqlalchemy.errors import SqlAlchemyConfigurationError


def _empty_options() -> Mapping[str, object]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class SqlAlchemySessionOptions:
    """Stable defaults applied to one root's async session factory."""

    expire_on_commit: bool = False
    autoflush: bool = False
    autobegin: bool = False

    def __post_init__(self) -> None:
        for name in ("expire_on_commit", "autoflush", "autobegin"):
            if not isinstance(getattr(self, name), bool):
                raise SqlAlchemyConfigurationError(f"session {name} must be boolean")


@dataclass(frozen=True, slots=True)
class SqlAlchemyOptions:
    """Configuration used to create one module-owned async engine."""

    url: str | URL = field(repr=False)
    engine_options: Mapping[str, object] = field(
        default_factory=_empty_options,
        repr=False,
    )
    session: SqlAlchemySessionOptions = SqlAlchemySessionOptions()

    def __post_init__(self) -> None:
        if not isinstance(self.url, str | URL):
            raise SqlAlchemyConfigurationError("url must be a string or SQLAlchemy URL")
        if isinstance(self.url, str) and not self.url:
            raise SqlAlchemyConfigurationError("url must not be empty")
        if not isinstance(self.engine_options, Mapping):
            raise SqlAlchemyConfigurationError("engine_options must be a mapping")
        copied = dict(self.engine_options)
        if any(not isinstance(key, str) for key in copied):
            raise SqlAlchemyConfigurationError("engine_options keys must be strings")
        if "url" in copied:
            raise SqlAlchemyConfigurationError("engine_options must not contain url")
        if not isinstance(self.session, SqlAlchemySessionOptions):
            raise SqlAlchemyConfigurationError(
                "session must be SqlAlchemySessionOptions"
            )
        object.__setattr__(self, "engine_options", MappingProxyType(copied))


__all__ = ["SqlAlchemyOptions", "SqlAlchemySessionOptions"]
