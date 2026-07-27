"""Public integration-specific failures."""

from nestpy import NestpyError


class SqlAlchemyIntegrationError(NestpyError):
    """Base class for Nestpy SQLAlchemy integration failures."""

    code = "sqlalchemy.integration_error"


class SqlAlchemyConfigurationError(SqlAlchemyIntegrationError):
    """Raised for invalid SQLAlchemy module configuration."""

    code = "sqlalchemy.configuration_error"


class TransactionContextError(SqlAlchemyIntegrationError):
    """Raised when an entity operation has no usable transaction context."""

    code = "sqlalchemy.transaction_context_error"


__all__ = [
    "SqlAlchemyConfigurationError",
    "SqlAlchemyIntegrationError",
    "TransactionContextError",
]
