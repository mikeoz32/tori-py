"""Public integration-specific failures."""

from nestpy import NestpyError


class SqlAlchemyIntegrationError(NestpyError):
    """Base class for Nestpy SQLAlchemy integration failures."""

    code = "sqlalchemy.integration_error"


class SqlAlchemyConfigurationError(SqlAlchemyIntegrationError):
    """Raised for invalid SQLAlchemy module configuration."""

    code = "sqlalchemy.configuration_error"


__all__ = ["SqlAlchemyConfigurationError", "SqlAlchemyIntegrationError"]
