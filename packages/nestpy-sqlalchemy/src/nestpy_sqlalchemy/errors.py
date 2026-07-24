"""Public integration-specific failures."""

from nestpy import NestpyError


class SqlAlchemyIntegrationError(NestpyError):
    """Base class for Nestpy SQLAlchemy integration failures."""

    code = "sqlalchemy.integration_error"


class SqlAlchemyConfigurationError(SqlAlchemyIntegrationError):
    """Raised for invalid SQLAlchemy module configuration."""

    code = "sqlalchemy.configuration_error"


class RepositoryBindingError(SqlAlchemyIntegrationError):
    """Raised when a repository cannot use the selected transaction."""

    code = "sqlalchemy.repository_binding_error"


__all__ = [
    "RepositoryBindingError",
    "SqlAlchemyConfigurationError",
    "SqlAlchemyIntegrationError",
]
